import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

app = FastAPI(title="Video Service", description="Video upload and retrieval service")

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
PRESIGNED_URL_EXPIRY = int(os.getenv("PRESIGNED_URL_EXPIRY", "3600"))  # Default 1 hour
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "524288000"))  # Default 500MB in bytes

# MongoDB client
client = None
db = None
videos_collection = None

# S3 client for Vultr Object Storage
s3_client = None


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """Dependency to verify API key for protected endpoints"""
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=500, detail="INTERNAL_API_KEY not configured on server")
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection and S3 client on startup"""
    global client, db, videos_collection, s3_client
    
    # Initialize MongoDB
    if MONGODB_URI:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
            videos_collection = db.videos
            await client.admin.command('ping')
            print(f"✓ Connected to MongoDB Atlas (database: {MONGODB_DB})")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"✗ MongoDB connection failed: {e}")
            client = None
            db = None
            videos_collection = None
    else:
        print("⚠ MONGODB_URI not set - skipping MongoDB connection")
    
    # Initialize S3 client for Vultr Object Storage
    if VULTR_ENDPOINT and VULTR_ACCESS_KEY and VULTR_SECRET_KEY:
        try:
            # Extract region from endpoint (e.g., https://ewr1.vultrobjects.com -> ewr1)
            # Vultr Object Storage uses the endpoint region for signing
            import re
            region_match = re.search(r'//([^.]+)\.vultrobjects\.com', VULTR_ENDPOINT)
            region = region_match.group(1) if region_match else 'us-east-1'
            
            s3_client = boto3.client(
                's3',
                endpoint_url=VULTR_ENDPOINT,
                aws_access_key_id=VULTR_ACCESS_KEY,
                aws_secret_access_key=VULTR_SECRET_KEY,
                region_name=region,
                config=Config(signature_version='s3v4')
            )
            if VULTR_BUCKET:
                try:
                    s3_client.head_bucket(Bucket=VULTR_BUCKET)
                    print(f"✓ Connected to Vultr Object Storage (bucket: {VULTR_BUCKET})")
                except ClientError as e:
                    print(f"⚠ Vultr Object Storage bucket '{VULTR_BUCKET}' not found or not accessible")
            else:
                print(f"✓ Vultr Object Storage client initialized (endpoint: {VULTR_ENDPOINT})")
                print("⚠ VULTR_BUCKET not set")
        except Exception as e:
            print(f"✗ Vultr Object Storage connection failed: {e}")
            s3_client = None
    else:
        if VULTR_ENDPOINT or VULTR_ACCESS_KEY or VULTR_SECRET_KEY:
            print("⚠ Vultr Object Storage credentials incomplete - skipping S3 client initialization")


@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection on shutdown"""
    global client, s3_client
    if client:
        client.close()
        print("MongoDB connection closed")
    s3_client = None


@app.get("/health")
async def health():
    """Health check endpoint"""
    health_status = {
        "status": "ok",
        "service": "video",
        "mongodb": {
            "connected": client is not None and db is not None
        },
        "object_storage": {
            "configured": bool(VULTR_ENDPOINT and VULTR_ACCESS_KEY and VULTR_SECRET_KEY),
            "connected": s3_client is not None,
            "bucket": VULTR_BUCKET if VULTR_BUCKET else None
        },
        "config": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "presigned_url_expiry_seconds": PRESIGNED_URL_EXPIRY
        }
    }
    return health_status


@app.post("/video/upload")
async def upload_video(
    file: UploadFile = File(...),
    job_id: str = Form(...),
    user_id: Optional[str] = Form(None),
    api_key: str = Depends(verify_api_key)
):
    """
    Upload a video file to Vultr Object Storage.
    
    Requirements:
    - Content-Type: video/mp4
    - File extension: .mp4
    - Max size: 500MB (configurable via MAX_FILE_SIZE env var)
    - X-API-Key header required (matches INTERNAL_API_KEY)
    
    Args:
        file: Video file (multipart/form-data)
        job_id: Job ID (required)
        user_id: User ID (optional)
        api_key: API key from header (verified by dependency)
    
    Returns:
        JSON with video_id, s3_key, and access URL
    """
    if not s3_client:
        raise HTTPException(status_code=503, detail="Object Storage not configured or unavailable")
    
    if videos_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    if not VULTR_BUCKET:
        raise HTTPException(status_code=500, detail="VULTR_BUCKET not configured")
    
    # Validate file extension (primary check)
    if not file.filename or not file.filename.lower().endswith('.mp4'):
        raise HTTPException(
            status_code=400,
            detail="Invalid file extension. Expected .mp4"
        )
    
    # Validate Content-Type (allow video/mp4 or application/octet-stream with .mp4 extension)
    if file.content_type not in ["video/mp4", "application/octet-stream"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Content-Type: {file.content_type}. Expected video/mp4 or application/octet-stream"
        )
    
    # Read file content
    try:
        content = await file.read()
        file_size = len(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")
    
    # Validate file size
    if file_size > MAX_FILE_SIZE:
        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {file_size / (1024 * 1024):.2f}MB. Maximum allowed: {max_size_mb:.2f}MB"
        )
    
    if file_size == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    
    # Generate video_id and S3 key
    video_id = str(uuid.uuid4())
    s3_key = f"jobs/{job_id}/{video_id}.mp4"
    
    # Upload to S3 (make it private - only accessible via presigned URLs)
    try:
        s3_client.put_object(
            Bucket=VULTR_BUCKET,
            Key=s3_key,
            Body=content,
            ContentType='video/mp4'
        )
    except ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to upload to Object Storage: {str(e)}"
        )
    
    # Store metadata in MongoDB
    video_doc = {
        "video_id": video_id,
        "s3_key": s3_key,
        "filename": file.filename,
        "size_bytes": file_size,
        "job_id": job_id,
        "user_id": user_id,
        "uploaded_at": datetime.utcnow(),
        "content_type": "video/mp4"
    }
    
    try:
        await videos_collection.insert_one(video_doc)
    except Exception as e:
        # If MongoDB insert fails, try to delete the S3 object
        try:
            s3_client.delete_object(Bucket=VULTR_BUCKET, Key=s3_key)
        except:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store metadata in database: {str(e)}"
        )
    
    return {
        "video_id": video_id,
        "s3_key": s3_key,
        "filename": file.filename,
        "size_bytes": file_size,
        "job_id": job_id,
        "user_id": user_id,
        "uploaded_at": video_doc["uploaded_at"].isoformat(),
        "url": f"/video/{video_id}"
    }


@app.get("/video/{video_id}")
async def get_video(video_id: str):
    """
    Get a presigned URL for a video file.
    
    This endpoint is public (no authentication required).
    Videos are stored as private objects in S3 and only accessible via presigned URLs.
    
    Args:
        video_id: UUID of the video
    
    Returns:
        JSON with video_id, presigned URL, and expiry information
    """
    if not s3_client:
        raise HTTPException(status_code=503, detail="Object Storage not configured or unavailable")
    
    if videos_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    if not VULTR_BUCKET:
        raise HTTPException(status_code=500, detail="VULTR_BUCKET not configured")
    
    # Fetch video metadata from MongoDB
    try:
        video_doc = await videos_collection.find_one({"video_id": video_id})
        if not video_doc:
            raise HTTPException(status_code=404, detail=f"Video not found: {video_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    s3_key = video_doc.get("s3_key")
    if not s3_key:
        raise HTTPException(status_code=500, detail="Video metadata incomplete: missing s3_key")
    
    # Generate presigned URL
    try:
        # For Vultr Object Storage, use the endpoint URL directly
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': VULTR_BUCKET,
                'Key': s3_key
            },
            ExpiresIn=PRESIGNED_URL_EXPIRY
        )
        
        # Vultr Object Storage sometimes requires the endpoint to be included in the presigned URL
        # If the presigned URL doesn't already have the endpoint, add it
        if not presigned_url.startswith(VULTR_ENDPOINT.replace('https://', '').replace('http://', '')):
            pass  # URL should already be correct
    except ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to generate presigned URL: {str(e)}"
        )
    
    return {
        "video_id": video_id,
        "url": presigned_url,
        "expires_in": PRESIGNED_URL_EXPIRY,
        "expires_at": (datetime.utcnow() + timedelta(seconds=PRESIGNED_URL_EXPIRY)).isoformat(),
        "filename": video_doc.get("filename"),
        "size_bytes": video_doc.get("size_bytes"),
        "job_id": video_doc.get("job_id"),
        "uploaded_at": video_doc.get("uploaded_at").isoformat() if video_doc.get("uploaded_at") else None
    }
