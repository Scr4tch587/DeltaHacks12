"""
Generator Worker Service

Polls MongoDB for queued generation jobs, calls the text_to_video API,
uploads results to DigitalOcean Spaces, and updates the database.
"""

import os
import time
import uuid
import glob
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import requests
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure
import boto3
from botocore.config import Config

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")

# Text-to-Video API
TEXT_TO_VIDEO_API_URL = os.getenv("TEXT_TO_VIDEO_API_URL", "http://text-to-video:8000")

# DigitalOcean Spaces Configuration
DO_SPACES_ENDPOINT = os.getenv("DO_SPACES_ENDPOINT", "https://tor1.digitaloceanspaces.com")
DO_SPACES_ACCESS_KEY = os.getenv("DO_SPACES_ACCESS_KEY", "")
DO_SPACES_SECRET_KEY = os.getenv("DO_SPACES_SECRET_KEY", "")
DO_SPACES_BUCKET = os.getenv("DO_SPACES_BUCKET", "deltahacks-videos")
DO_SPACES_REGION = os.getenv("DO_SPACES_REGION", "tor1")
DO_SPACES_CDN_URL = os.getenv("DO_SPACES_CDN_URL", "https://deltahacks-videos.tor1.cdn.digitaloceanspaces.com")

# Worker Configuration
WORKER_ID = os.getenv("WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")
POLL_INTERVAL_S = int(os.getenv("POLL_INTERVAL_S", "5"))
JOB_TIMEOUT_MINUTES = int(os.getenv("JOB_TIMEOUT_MINUTES", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Temp directory for video output
TEMP_OUTPUT_DIR = os.getenv("TEMP_OUTPUT_DIR", "/tmp/generator_output")


def get_mongo_client():
    """Initialize MongoDB connection."""
    if not MONGODB_URI:
        raise ValueError("MONGODB_URI not set")
    
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ping')
    return client


def get_s3_client():
    """Initialize S3 client for DigitalOcean Spaces."""
    if not DO_SPACES_ACCESS_KEY or not DO_SPACES_SECRET_KEY:
        raise ValueError("DO_SPACES credentials not set")
    
    return boto3.client(
        's3',
        endpoint_url=DO_SPACES_ENDPOINT,
        aws_access_key_id=DO_SPACES_ACCESS_KEY,
        aws_secret_access_key=DO_SPACES_SECRET_KEY,
        region_name=DO_SPACES_REGION,
        config=Config(signature_version='s3v4')
    )


def claim_job(generation_jobs_collection):
    """
    Atomically claim a queued job.
    
    Returns the claimed job document, or None if no jobs available.
    """
    # Find and claim a queued job
    job = generation_jobs_collection.find_one_and_update(
        {
            "status": "queued",
            # Add small delay to avoid race conditions
            "created_at": {"$lt": datetime.utcnow() - timedelta(seconds=2)}
        },
        {
            "$set": {
                "status": "running",
                "started_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "worker_id": WORKER_ID
            }
        },
        sort=[("created_at", 1)],  # FIFO
        return_document=ReturnDocument.AFTER
    )
    
    return job


def reset_stale_jobs(generation_jobs_collection):
    """Reset jobs stuck in 'running' status for too long (worker crash recovery)."""
    stale_threshold = datetime.utcnow() - timedelta(minutes=JOB_TIMEOUT_MINUTES)
    
    result = generation_jobs_collection.update_many(
        {
            "status": "running",
            "started_at": {"$lt": stale_threshold}
        },
        {
            "$set": {
                "status": "queued",
                "updated_at": datetime.utcnow(),
                "worker_id": None,
                "started_at": None
            },
            "$inc": {"retry_count": 1}
        }
    )
    
    if result.modified_count > 0:
        print(f"[{WORKER_ID}] Reset {result.modified_count} stale jobs")


def update_job_status(generation_jobs_collection, job_id: str, status: str, error: str = None):
    """Update job status."""
    update = {
        "$set": {
            "status": status,
            "updated_at": datetime.utcnow()
        }
    }
    
    if status in ["ready", "failed"]:
        update["$set"]["completed_at"] = datetime.utcnow()
    
    if error:
        update["$set"]["error"] = error
    
    generation_jobs_collection.update_one(
        {"job_id": job_id},
        update
    )


def generate_video(job_description: str, output_video_id: str) -> str:
    """
    Call the text_to_video API to generate a video.
    
    Returns the path to the HLS output directory.
    """
    output_path = os.path.join(TEMP_OUTPUT_DIR, output_video_id)
    os.makedirs(output_path, exist_ok=True)
    
    # Call the text_to_video API
    response = requests.post(
        f"{TEXT_TO_VIDEO_API_URL}/generate",
        json={
            "job_description": job_description,
            "output_path": output_path,
            "output_name": output_video_id
        },
        timeout=300  # 5 minute timeout for video generation
    )
    
    if response.status_code != 200:
        raise Exception(f"Video generation failed: {response.text}")
    
    result = response.json()
    video_path = result.get("video_path")
    
    if not video_path:
        raise Exception("No video path returned from API")
    
    # The video_path points to master.m3u8, get the HLS directory
    hls_dir = os.path.dirname(video_path)
    
    return hls_dir


def upload_hls_to_spaces(s3_client, hls_dir: str, video_id: str) -> dict:
    """
    Upload HLS directory to DigitalOcean Spaces.
    
    Returns dict with s3_key and cdn_url.
    """
    uploaded_files = []
    
    # Walk the HLS directory and upload all files
    hls_path = Path(hls_dir)
    
    for file_path in hls_path.rglob("*"):
        if file_path.is_file():
            # Calculate the relative path from HLS dir
            rel_path = file_path.relative_to(hls_path)
            s3_key = f"hls/{video_id}/{rel_path}"
            
            # Determine content type
            suffix = file_path.suffix.lower()
            content_types = {
                ".m3u8": "application/vnd.apple.mpegurl",
                ".ts": "video/mp2t",
                ".jpg": "image/jpeg",
                ".png": "image/png",
            }
            content_type = content_types.get(suffix, "application/octet-stream")
            
            # Upload with public-read ACL
            with open(file_path, "rb") as f:
                s3_client.put_object(
                    Bucket=DO_SPACES_BUCKET,
                    Key=s3_key,
                    Body=f,
                    ContentType=content_type,
                    ACL="public-read",
                    CacheControl="public, max-age=31536000"  # 1 year cache
                )
            
            uploaded_files.append(s3_key)
            print(f"  Uploaded: {s3_key}")
    
    # Return the master manifest path
    s3_key = f"hls/{video_id}/master.m3u8"
    cdn_url = f"{DO_SPACES_CDN_URL}/hls/{video_id}/master.m3u8"
    
    return {
        "s3_key": s3_key,
        "cdn_url": cdn_url,
        "uploaded_files": len(uploaded_files)
    }


def create_video_document(videos_collection, job: dict, upload_result: dict) -> str:
    """
    Insert video document into MongoDB.
    
    Returns the video_id.
    """
    # video_id = greenhouse_id (they are the same)
    video_id = job["output_video_id"]  # Already set to greenhouse_id by backend
    
    # Store as integer if possible to match jobs collection
    try:
        video_id = int(video_id)
    except (ValueError, TypeError):
        pass
    
    video_doc = {
        "video_id": video_id,
        "s3_key": upload_result["s3_key"],
        "cdn_url": upload_result["cdn_url"],
        "template_id": job.get("template_id", "unknown"),
        "status": "ready",
        "created_at": datetime.utcnow(),
        "generation_job_id": job["job_id"]
    }
    
    videos_collection.insert_one(video_doc)
    
    return str(video_id)


def process_job(job: dict, db, s3_client) -> bool:
    """
    Process a single generation job.
    
    Returns True if successful, False otherwise.
    """
    job_id = job["job_id"]
    greenhouse_id = job["greenhouse_id"]
    output_video_id = job["output_video_id"]
    
    generation_jobs = db.generation_jobs
    videos = db.videos
    jobs = db.jobs
    
    print(f"[{WORKER_ID}] Processing job {job_id} for greenhouse_id={greenhouse_id}")
    
    try:
        # Step 1: Get job description from jobs collection
        # greenhouse_id may be stored as int in the database, so try both
        job_doc = jobs.find_one({"greenhouse_id": greenhouse_id})
        if not job_doc:
            # Try as integer
            try:
                job_doc = jobs.find_one({"greenhouse_id": int(greenhouse_id)})
            except (ValueError, TypeError):
                pass
        if not job_doc:
            raise Exception(f"Job {greenhouse_id} not found in database")
        
        # Try both field names - some jobs use 'description', others use 'description_text'
        job_description = job_doc.get("description_text") or job_doc.get("description", "")
        if not job_description or len(job_description) < 50:
            raise Exception(f"Job description too short ({len(job_description)} chars)")
        
        print(f"  Job description: {job_description[:100]}...")
        
        # Step 2: Generate video via text_to_video API
        print(f"  Generating video...")
        update_job_status(generation_jobs, job_id, "running")
        
        hls_dir = generate_video(job_description, output_video_id)
        print(f"  Video generated at: {hls_dir}")
        
        # Step 3: Upload to DigitalOcean Spaces
        print(f"  Uploading to DigitalOcean Spaces...")
        update_job_status(generation_jobs, job_id, "uploaded")
        
        upload_result = upload_hls_to_spaces(s3_client, hls_dir, output_video_id)
        print(f"  Uploaded {upload_result['uploaded_files']} files")
        
        # Step 4: Create video document in MongoDB
        print(f"  Creating video document...")
        update_job_status(generation_jobs, job_id, "indexed")
        
        create_video_document(videos, job, upload_result)
        
        # Step 5: Mark job as ready
        update_job_status(generation_jobs, job_id, "ready")
        print(f"  Job {job_id} completed successfully!")
        
        # Cleanup temp files
        temp_dir = os.path.join(TEMP_OUTPUT_DIR, output_video_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"  ERROR: {error_msg}")
        
        # Check if we should retry
        retry_count = job.get("retry_count", 0)
        if retry_count < MAX_RETRIES:
            # Reset to queued for retry
            generation_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "queued",
                        "updated_at": datetime.utcnow(),
                        "error": error_msg,
                        "worker_id": None,
                        "started_at": None
                    },
                    "$inc": {"retry_count": 1}
                }
            )
            print(f"  Queued for retry ({retry_count + 1}/{MAX_RETRIES})")
        else:
            # Mark as failed
            update_job_status(generation_jobs, job_id, "failed", error_msg)
            print(f"  Marked as failed (max retries exceeded)")
        
        return False


def run_worker():
    """Main worker loop."""
    print(f"[{WORKER_ID}] Starting generator worker...")
    print(f"  MongoDB: {MONGODB_URI[:30]}...")
    print(f"  Text-to-Video API: {TEXT_TO_VIDEO_API_URL}")
    print(f"  DO Spaces: {DO_SPACES_BUCKET}")
    print(f"  Poll interval: {POLL_INTERVAL_S}s")
    
    # Initialize connections
    try:
        mongo_client = get_mongo_client()
        db = mongo_client[MONGODB_DB]
        print(f"[{WORKER_ID}] Connected to MongoDB")
    except Exception as e:
        print(f"[{WORKER_ID}] Failed to connect to MongoDB: {e}")
        return
    
    try:
        s3_client = get_s3_client()
        # Test connection
        s3_client.head_bucket(Bucket=DO_SPACES_BUCKET)
        print(f"[{WORKER_ID}] Connected to DigitalOcean Spaces")
    except Exception as e:
        print(f"[{WORKER_ID}] Failed to connect to DO Spaces: {e}")
        return
    
    generation_jobs = db.generation_jobs
    
    # Create temp directory
    os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)
    
    print(f"[{WORKER_ID}] Worker ready, polling for jobs...")
    
    last_stale_check = datetime.utcnow()
    
    while True:
        try:
            # Periodically check for stale jobs (every 5 minutes)
            if datetime.utcnow() - last_stale_check > timedelta(minutes=5):
                reset_stale_jobs(generation_jobs)
                last_stale_check = datetime.utcnow()
            
            # Try to claim a job
            job = claim_job(generation_jobs)
            
            if job:
                process_job(job, db, s3_client)
            else:
                # No jobs available, wait before polling again
                time.sleep(POLL_INTERVAL_S)
                
        except ConnectionFailure as e:
            print(f"[{WORKER_ID}] MongoDB connection lost: {e}")
            print(f"[{WORKER_ID}] Attempting to reconnect...")
            time.sleep(5)
            try:
                mongo_client = get_mongo_client()
                db = mongo_client[MONGODB_DB]
                generation_jobs = db.generation_jobs
                print(f"[{WORKER_ID}] Reconnected to MongoDB")
            except Exception as reconnect_error:
                print(f"[{WORKER_ID}] Reconnect failed: {reconnect_error}")
                time.sleep(10)
                
        except KeyboardInterrupt:
            print(f"[{WORKER_ID}] Shutting down...")
            break
            
        except Exception as e:
            print(f"[{WORKER_ID}] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
