import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Header, Depends, Query
from fastapi.responses import JSONResponse, Response, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from app.s3_client import get_s3_client, get_presigned_url, fetch_object
from app.hls_rewrite import rewrite_playlist

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
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
PRESIGNED_URL_EXPIRY = int(os.getenv("PRESIGNED_URL_EXPIRY", "3600"))  # Default 1 hour
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "524288000"))  # Default 500MB in bytes
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")  # Base URL for HLS gateway (e.g., http://localhost:8002)

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


@app.get("/hls/{key:path}")
async def get_hls_playlist(key: str):
    """
    Fetch and rewrite HLS playlist from S3.
    
    This endpoint fetches a playlist from Vultr Object Storage and rewrites all URIs
    to point to our API gateway endpoints.
    
    Args:
        key: S3 key path (e.g., "hls/abc123/master.m3u8")
    
    Returns:
        Rewritten playlist with correct Content-Type headers
    """
    # Security: ensure key starts with hls/
    if not key.startswith("hls/"):
        raise HTTPException(status_code=400, detail="Key must start with 'hls/'")
    
    try:
        # Fetch playlist from S3
        playlist_content = fetch_object(key)
        playlist_text = playlist_content.decode('utf-8')
        
        # Get API base URL (empty string for relative paths, or PUBLIC_BASE_URL if set)
        api_base = PUBLIC_BASE_URL.rstrip('/') if PUBLIC_BASE_URL else ""
        
        # Rewrite the playlist
        rewritten = rewrite_playlist(playlist_text, key, api_base)
        
        # Count rewritten URIs for logging
        original_lines = playlist_text.split('\n')
        rewritten_lines = rewritten.split('\n')
        uri_count = sum(1 for line in original_lines if line.strip() and not line.strip().startswith('#'))
        
        # Log
        print(f"[HLS] Served playlist: key={key}, size={len(playlist_content)} bytes, rewritten_uris={uri_count}")
        
        # Return with correct headers
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Cache-Control": "no-store",
            }
        )
    
    except Exception as e:
        error_msg = str(e)
        print(f"[HLS] Error serving playlist key={key}: {error_msg}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch playlist: {error_msg}")


@app.get("/hls-seg/{key:path}")
async def get_hls_segment(key: str):
    """
    Generate presigned URL and redirect to segment.
    
    This endpoint generates a presigned URL for an HLS segment and redirects
    the client to download it directly from Vultr Object Storage.
    
    Args:
        key: S3 key path (e.g., "hls/abc123/720p/seg_000.ts")
    
    Returns:
        307 redirect to presigned URL
    """
    # Security: ensure key starts with hls/
    if not key.startswith("hls/"):
        raise HTTPException(status_code=400, detail="Key must start with 'hls/'")
    
    try:
        from app.s3_client import PRESIGN_EXPIRES_SECONDS
        # Generate presigned URL
        presigned_url = get_presigned_url(key, expires_in=PRESIGN_EXPIRES_SECONDS)
        
        # Log (first 80 chars only)
        url_preview = presigned_url[:80] + "..." if len(presigned_url) > 80 else presigned_url
        print(f"[HLS-SEG] Redirect: key={key}, url_preview={url_preview}")
        
        # Return 307 redirect (preserves method)
        # Use 302 for better compatibility with some video players
        return RedirectResponse(
            url=presigned_url,
            status_code=302,  # Changed from 307 to 302 for better video player compatibility
            headers={
                "Cache-Control": "private, max-age=60",
                "Access-Control-Allow-Origin": "*",  # Ensure CORS for redirects
            }
        )
    
    except Exception as e:
        error_msg = str(e)
        print(f"[HLS-SEG] Error generating presigned URL key={key}: {error_msg}")
        raise HTTPException(status_code=502, detail=f"Failed to generate presigned URL: {error_msg}")


@app.head("/hls-seg/{key:path}")
async def head_hls_segment(key: str):
    """
    HEAD request for HLS segment (for debugging).
    
    Args:
        key: S3 key path
    
    Returns:
        HEAD response with redirect location
    """
    # Security: ensure key starts with hls/
    if not key.startswith("hls/"):
        raise HTTPException(status_code=400, detail="Key must start with 'hls/'")
    
    try:
        from app.s3_client import PRESIGN_EXPIRES_SECONDS
        presigned_url = get_presigned_url(key, expires_in=PRESIGN_EXPIRES_SECONDS)
        
        # Return HEAD response with Location header
        return Response(
            status_code=302,
            headers={
                "Location": presigned_url,
                "Cache-Control": "private, max-age=60",
                "Access-Control-Allow-Origin": "*",
            }
        )
    
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(status_code=502, detail=f"Failed to generate presigned URL: {error_msg}")


@app.get("/hls-debug/presign")
async def debug_presign(key: str = Query(...), api_key: str = Depends(verify_api_key)):
    """
    Debug endpoint to test presigned URL generation.
    
    Protected endpoint that returns the resolved key and presigned URL
    for debugging purposes.
    
    Args:
        key: S3 key to generate presigned URL for
        api_key: API key from header (verified by dependency)
    
    Returns:
        JSON with resolved key and presigned URL
    """
    # Security: ensure key starts with hls/
    if not key.startswith("hls/"):
        raise HTTPException(status_code=400, detail="Key must start with 'hls/'")
    
    try:
        from app.s3_client import PRESIGN_EXPIRES_SECONDS, S3_ADDRESSING_STYLE, get_s3_key, S3_KEY_PREFIX, VULTR_BUCKET as S3_BUCKET
        from urllib.parse import urlparse
        
        presigned_url = get_presigned_url(key, expires_in=PRESIGN_EXPIRES_SECONDS)
        
        # Extract host from URL for debugging
        parsed = urlparse(presigned_url)
        
        resolved_key = get_s3_key(key)
        
        return {
            "input_key": key,
            "resolved_key": resolved_key,
            "presigned_url": presigned_url,
            "host": parsed.netloc,
            "expires_in_seconds": PRESIGN_EXPIRES_SECONDS,
            "addressing_style": S3_ADDRESSING_STYLE,
            "bucket": S3_BUCKET,
            "key_prefix": S3_KEY_PREFIX,
        }
    
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=f"Debug presign failed: {error_msg}")


@app.get("/video/{video_id}")
async def get_video(video_id: str):
    """
    Get HLS playback URLs for a video.
    
    This endpoint is public (no authentication required).
    Returns absolute URL to the master playlist via our HLS gateway.
    
    Args:
        video_id: The video ID (greenhouse_id) used as the folder name in HLS storage
    
    Returns:
        JSON with video_id, playback URLs (HLS manifest and poster), and metadata
    """
    if not PUBLIC_BASE_URL:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL not configured"
        )
    
    base_url = PUBLIC_BASE_URL.rstrip('/')
    
    # Construct HLS URLs (keeping hls/ prefix, so it becomes /hls/hls/{video_id}/master.m3u8)
    hls_key = f"hls/{video_id}/master.m3u8"
    playback_url = f"{base_url}/hls/{hls_key}"
    
    # Poster URL (also via gateway)
    poster_key = f"hls/{video_id}/poster.jpg"
    poster_url = f"{base_url}/hls-seg/{poster_key}"
    
    return {
        "video_id": video_id,
        "playback": {
            "type": "hls",
            "url": playback_url
        },
        "poster_url": poster_url,
        "duration_s": None,
        "aspect_ratio": "9:16"
    }
