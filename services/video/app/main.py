import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

app = FastAPI(title="Video Service", description="Video upload and retrieval service")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for hackathon
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "524288000"))  # Default 500MB in bytes

# DigitalOcean Spaces CDN Configuration
# CDN endpoint provides global edge caching for low-latency video delivery
DO_SPACES_CDN_URL = os.getenv("DO_SPACES_CDN_URL", "https://deltahacks-videos.tor1.cdn.digitaloceanspaces.com")

# DigitalOcean Spaces S3-compatible configuration (for uploads if needed)
DO_SPACES_ENDPOINT = os.getenv("DO_SPACES_ENDPOINT", "https://tor1.digitaloceanspaces.com")
DO_SPACES_ACCESS_KEY = os.getenv("DO_SPACES_ACCESS_KEY", "")
DO_SPACES_SECRET_KEY = os.getenv("DO_SPACES_SECRET_KEY", "")
DO_SPACES_BUCKET = os.getenv("DO_SPACES_BUCKET", "deltahacks-videos")
DO_SPACES_REGION = os.getenv("DO_SPACES_REGION", "tor1")

# MongoDB client
client = None
db = None
videos_collection = None

# S3 client for DigitalOcean Spaces
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
    
    # Initialize S3 client for DigitalOcean Spaces (for uploads)
    if DO_SPACES_ACCESS_KEY and DO_SPACES_SECRET_KEY:
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=DO_SPACES_ENDPOINT,
                aws_access_key_id=DO_SPACES_ACCESS_KEY,
                aws_secret_access_key=DO_SPACES_SECRET_KEY,
                region_name=DO_SPACES_REGION,
                config=Config(signature_version='s3v4')
            )
            try:
                s3_client.head_bucket(Bucket=DO_SPACES_BUCKET)
                print(f"✓ Connected to DigitalOcean Spaces (bucket: {DO_SPACES_BUCKET})")
            except ClientError as e:
                print(f"⚠ DigitalOcean Spaces bucket '{DO_SPACES_BUCKET}' not found or not accessible")
        except Exception as e:
            print(f"✗ DigitalOcean Spaces connection failed: {e}")
            s3_client = None
    else:
        print("⚠ DO_SPACES credentials not set - uploads disabled")
    
    # Log CDN configuration
    print(f"✓ CDN configured: {DO_SPACES_CDN_URL}")


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
            "cdn_url": DO_SPACES_CDN_URL,
            "bucket": DO_SPACES_BUCKET,
            "upload_enabled": s3_client is not None
        },
        "config": {
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
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
    Upload a video file to DigitalOcean Spaces.
    
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
    
    # Upload to S3 with public-read ACL
    try:
        s3_client.put_object(
            Bucket=DO_SPACES_BUCKET,
            Key=s3_key,
            Body=content,
            ContentType='video/mp4',
            ACL='public-read'
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
            s3_client.delete_object(Bucket=DO_SPACES_BUCKET, Key=s3_key)
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


@app.get("/video/{greenhouse_id}")
async def get_video(greenhouse_id: str):
    """
    Get HLS playback URLs for a video by greenhouse_id.

    Returns direct CDN URLs for HLS playback. No presigned URLs or redirects needed
    since DigitalOcean Spaces CDN serves content publicly with edge caching.

    Benefits:
    - Low latency: CDN edge caching near users
    - No redirects: Direct URLs in playlist
    - Simple: No presigned URL generation or playlist rewriting

    Args:
        greenhouse_id: The greenhouse job ID to look up the video

    Returns:
        JSON with video_id, playback URLs (HLS manifest and poster), and metadata
    """
    if not videos_collection:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Convert greenhouse_id to int if it looks like a number
    try:
        gh_id_int = int(greenhouse_id)
    except ValueError:
        gh_id_int = None
    
    # Look up video by greenhouse_id (try both string and int)
    video = await videos_collection.find_one({
        "greenhouse_id": {"$in": [greenhouse_id, gh_id_int] if gh_id_int else [greenhouse_id]},
        "status": "ready"
    })
    
    if not video:
        raise HTTPException(status_code=404, detail=f"Video not found for greenhouse_id {greenhouse_id}")
    
    # Use the video_id (UUID) from the database for the actual file path
    actual_video_id = video.get("video_id")
    if not actual_video_id:
        raise HTTPException(status_code=500, detail="Video document missing video_id")
    
    cdn_base = DO_SPACES_CDN_URL.rstrip('/')

    # Construct direct CDN URLs using the actual video_id
    playback_url = f"{cdn_base}/hls/{actual_video_id}/master.m3u8"
    poster_url = f"{cdn_base}/hls/{actual_video_id}/poster.jpg"

    return {
        "video_id": greenhouse_id,  # Return greenhouse_id for client compatibility
        "playback": {
            "type": "hls",
            "url": playback_url
        },
        "poster_url": poster_url,
        "duration_s": None,
        "aspect_ratio": "9:16"
    }
