import os
import hashlib
import uuid
import random
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, DuplicateKeyError, OperationFailure
from pydantic import BaseModel, EmailStr
from bson import ObjectId
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import google.generativeai as genai
from .auth import verify_password, get_password_hash, create_access_token, verify_token

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")

# Vultr Object Storage (S3-compatible) variables
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "")

# Gemini API configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSION = 768

# On-demand generation configuration
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.75"))
TARGET_COUNT = int(os.getenv("TARGET_COUNT", "5"))
MAX_GENERATE_PER_REQUEST = int(os.getenv("MAX_GENERATE_PER_REQUEST", "5"))
MAX_USER_CONCURRENT_JOBS = int(os.getenv("MAX_USER_CONCURRENT_JOBS", "2"))
VECTOR_SEARCH_LIMIT = int(os.getenv("VECTOR_SEARCH_LIMIT", "20"))
VECTOR_SEARCH_CANDIDATES = int(os.getenv("VECTOR_SEARCH_CANDIDATES", "50"))

# Available video templates for random selection
VIDEO_TEMPLATES = [
    "family_guy",
    "spongebob",
    "political",
]

# MongoDB client (will be initialized on startup)
client = None
db = None
users_collection = None
user_job_views_collection = None
jobs_collection = None
videos_collection = None
generation_jobs_collection = None

# S3 client for Vultr Object Storage
s3_client = None


# ============================================================================
# Utility Functions
# ============================================================================

def compute_query_fingerprint(query: str) -> str:
    """
    Normalize and hash query for deduplication.
    
    Steps:
    1. Lowercase
    2. Strip whitespace
    3. Remove punctuation
    4. Sort words (order-independent matching)
    5. SHA256 hash, truncate to 16 chars
    """
    normalized = query.lower().strip()
    # Remove punctuation, keep only alphanumeric and spaces
    normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
    # Sort words for order-independence
    words = sorted(normalized.split())
    canonical = ' '.join(words)
    # Hash and truncate
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# Pydantic models for request/response
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    prompt: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    email: str


class MarkSeenRequest(BaseModel):
    user_id: str
    greenhouse_id: str


class UserJobViewResponse(BaseModel):
    user_id: str
    greenhouse_id: str
    seen: bool


class BulkCheckRequest(BaseModel):
    user_id: str
    greenhouse_ids: List[str]


class SearchJobsRequest(BaseModel):
    text_prompt: str
    user_id: str


class SearchJobsResponse(BaseModel):
    user_id: str
    greenhouse_ids: List[str]
    count: int
    generation_triggered: bool = False
    generation_job_ids: List[str] = []


@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection, S3 client, and Gemini API on startup"""
    global client, db, s3_client, users_collection, user_job_views_collection, jobs_collection
    global videos_collection, generation_jobs_collection
    
    # Initialize MongoDB
    if MONGODB_URI:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
            # Test the connection
            await client.admin.command('ping')
            print(f"✓ Connected to MongoDB Atlas (database: {MONGODB_DB})")
            
            # Initialize users collection and create unique index on email
            users_collection = db.users
            try:
                await users_collection.create_index([("email", 1)], unique=True, name="email_unique_idx")
                print("✓ users collection initialized with index")
            except Exception as e:
                # Index already exists with a different name - check if it's the same index
                error_str = str(e)
                if "Index already exists" in error_str or "IndexOptionsConflict" in error_str or isinstance(e, OperationFailure):
                    # Check if there's already a unique index on email
                    try:
                        existing_indexes = await users_collection.list_indexes().to_list(length=10)
                        email_index_exists = any(
                            idx.get("key", {}).get("email") == 1 and idx.get("unique") is True
                            for idx in existing_indexes
                        )
                        if email_index_exists:
                            print("✓ users collection already has unique email index")
                        else:
                            # Try to drop old index and create new one
                            try:
                                await users_collection.drop_index("email_1")
                                await users_collection.create_index([("email", 1)], unique=True, name="email_unique_idx")
                                print("✓ users collection index updated")
                            except Exception as drop_error:
                                print(f"⚠ Could not update email index: {drop_error}")
                                print("  Index exists but may have different name - continuing anyway")
                    except Exception as list_error:
                        print(f"⚠ Could not check existing indexes: {list_error}")
                        print("  Continuing anyway - index may already exist")
                else:
                    # Re-raise if it's not an index conflict error
                    raise
            
            # Initialize user_job_views collection and create index
            user_job_views_collection = db.user_job_views
            # Create compound index on (user_id, greenhouse_id) for fast lookups
            await user_job_views_collection.create_index(
                [("user_id", 1), ("greenhouse_id", 1)],
                unique=True,
                name="user_greenhouse_unique_idx"
            )
            print("✓ user_job_views collection initialized with index")
            
            # Initialize jobs collection
            jobs_collection = db.jobs
            print("✓ jobs collection initialized")
            
            # Initialize videos collection with indexes
            videos_collection = db.videos
            try:
                # Index on greenhouse_id for fast lookup of videos by job
                await videos_collection.create_index(
                    [("greenhouse_id", 1)],
                    name="greenhouse_id_idx"
                )
                # Unique index on video_id
                await videos_collection.create_index(
                    [("video_id", 1)],
                    unique=True,
                    name="video_id_unique_idx"
                )
                # Index for status queries
                await videos_collection.create_index(
                    [("status", 1), ("created_at", -1)],
                    name="status_created_idx"
                )
                print("✓ videos collection initialized with indexes")
            except OperationFailure as e:
                if "Index already exists" in str(e) or "IndexOptionsConflict" in str(e):
                    print("✓ videos collection indexes already exist")
                else:
                    raise
            
            # Initialize generation_jobs collection with indexes
            generation_jobs_collection = db.generation_jobs
            try:
                # Index for worker polling (find queued jobs)
                await generation_jobs_collection.create_index(
                    [("status", 1), ("created_at", 1)],
                    name="status_created_idx"
                )
                # Index for deduplication
                await generation_jobs_collection.create_index(
                    [("query_fingerprint", 1), ("greenhouse_id", 1)],
                    name="fingerprint_greenhouse_idx"
                )
                # Index for per-user concurrency check
                await generation_jobs_collection.create_index(
                    [("user_id", 1), ("status", 1)],
                    name="user_status_idx"
                )
                # TTL index - auto-delete jobs after 24 hours
                await generation_jobs_collection.create_index(
                    [("created_at", 1)],
                    expireAfterSeconds=86400,  # 24 hours
                    name="ttl_idx"
                )
                print("✓ generation_jobs collection initialized with indexes")
            except OperationFailure as e:
                if "Index already exists" in str(e) or "IndexOptionsConflict" in str(e):
                    print("✓ generation_jobs collection indexes already exist")
                else:
                    raise
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"✗ MongoDB connection failed: {e}")
            client = None
            db = None
            users_collection = None
            user_job_views_collection = None
            jobs_collection = None
    else:
        print("⚠ MONGODB_URI not set - skipping MongoDB connection")
    
    # Initialize Gemini API
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            print(f"✓ Gemini API configured (model: {EMBEDDING_MODEL})")
        except Exception as e:
            print(f"✗ Gemini API configuration failed: {e}")
    else:
        print("⚠ GEMINI_API_KEY not set - skipping Gemini API configuration")
    
    # Initialize S3 client for Vultr Object Storage
    if VULTR_ENDPOINT and VULTR_ACCESS_KEY and VULTR_SECRET_KEY:
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=VULTR_ENDPOINT,
                aws_access_key_id=VULTR_ACCESS_KEY,
                aws_secret_access_key=VULTR_SECRET_KEY
            )
            # Test the connection by listing buckets (or checking if our bucket exists)
            if VULTR_BUCKET:
                try:
                    s3_client.head_bucket(Bucket=VULTR_BUCKET)
                    print(f"✓ Connected to Vultr Object Storage (bucket: {VULTR_BUCKET})")
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == '404':
                        print(f"⚠ Vultr Object Storage bucket '{VULTR_BUCKET}' not found")
                    else:
                        print(f"⚠ Vultr Object Storage connection issue: {e}")
            else:
                print(f"✓ Vultr Object Storage client initialized (endpoint: {VULTR_ENDPOINT})")
                print("⚠ VULTR_BUCKET not set - cannot test bucket access")
        except Exception as e:
            print(f"✗ Vultr Object Storage connection failed: {e}")
            s3_client = None
    else:
        if VULTR_ENDPOINT or VULTR_ACCESS_KEY or VULTR_SECRET_KEY:
            print("⚠ Vultr Object Storage credentials incomplete - skipping S3 client initialization")
        # else: silently skip if nothing is set


@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection on shutdown"""
    global client, s3_client
    if client:
        client.close()
        print("MongoDB connection closed")
    # S3 client doesn't need explicit cleanup, but we can reset it
    s3_client = None


@app.get("/health")
async def health():
    """Health check endpoint - returns service, DB, and Object Storage status"""
    health_status = {
        "status": "ok",
        "service": "backend",
        "mongodb": {
            "connected": False,
            "database": MONGODB_DB if MONGODB_URI else None
        },
        "object_storage": {
            "configured": False,
            "connected": False,
            "endpoint": VULTR_ENDPOINT if VULTR_ENDPOINT else None,
            "bucket": VULTR_BUCKET if VULTR_BUCKET else None
        }
    }
    
    # Test MongoDB connection if client exists
    if client:
        try:
            await client.admin.command('ping')
            health_status["mongodb"]["connected"] = True
        except Exception as e:
            health_status["mongodb"]["error"] = str(e)
    elif not MONGODB_URI:
        health_status["mongodb"]["error"] = "MONGODB_URI not configured"
    else:
        health_status["mongodb"]["error"] = "Connection not initialized"
    
    # Test Object Storage connection
    if VULTR_ENDPOINT and VULTR_ACCESS_KEY and VULTR_SECRET_KEY:
        health_status["object_storage"]["configured"] = True
        if s3_client:
            try:
                # Quick test: list buckets or check bucket access
                if VULTR_BUCKET:
                    s3_client.head_bucket(Bucket=VULTR_BUCKET)
                    health_status["object_storage"]["connected"] = True
                else:
                    # Just verify we can make a call
                    s3_client.list_buckets()
                    health_status["object_storage"]["connected"] = True
            except Exception as e:
                health_status["object_storage"]["error"] = str(e)
        else:
            health_status["object_storage"]["error"] = "S3 client not initialized"
    else:
        health_status["object_storage"]["error"] = "Object Storage credentials not configured"
    
    return health_status


@app.get("/health/db")
async def health_db():
    """Dedicated MongoDB connection test endpoint - tests handshake (ping)"""
    global client, db
    
    if not MONGODB_URI:
        raise HTTPException(
            status_code=500, 
            detail="MONGODB_URI not configured. Set the MONGODB_URI environment variable."
        )
    
    # Try to initialize connection if it wasn't set during startup
    if not client:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
            print("✓ MongoDB client initialized on-demand (was not set during startup)")
        except Exception as e:
            raise HTTPException(
                status_code=503, 
                detail=f"MongoDB client initialization failed: {str(e)}. Check connection string and network."
            )
    
    try:
        # Ping the database (handshake test) - this is the core connection test
        result = await client.admin.command('ping')
        
        response = {
            "status": "connected",
            "mongodb_uri_set": bool(MONGODB_URI),
            "database": MONGODB_DB,
            "ping": result,
            "handshake": "success"
        }
        
        # Try to get database info (optional - might fail due to permissions)
        if db is not None:
            try:
                db_info = await db.command('dbStats')
                response["database_stats"] = {
                    "name": db_info.get("db", MONGODB_DB),
                    "collections": db_info.get("collections", 0),
                    "data_size": db_info.get("dataSize", 0)
                }
            except Exception as db_stats_error:
                # dbStats failed but ping succeeded - connection is still healthy
                response["database_stats"] = {
                    "note": f"dbStats unavailable: {str(db_stats_error)} (connection is still healthy)"
                }
        else:
            response["note"] = f"Database object not initialized (database: {MONGODB_DB})"
        
        return response
        
    except ConnectionFailure as e:
        raise HTTPException(
            status_code=503, 
            detail=f"MongoDB connection failed: {str(e)}. Check your connection string and network."
        )
    except ServerSelectionTimeoutError as e:
        raise HTTPException(
            status_code=503, 
            detail=f"MongoDB server selection timeout: {str(e)}. Possible causes: network issue, firewall blocking, or IP not whitelisted in MongoDB Atlas."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"MongoDB error ({type(e).__name__}): {str(e)}"
        )


@app.get("/health/db/ping")
async def health_db_ping():
    """Minimal MongoDB handshake test - just ping, no additional info"""
    global client, db
    
    if not MONGODB_URI:
        raise HTTPException(status_code=500, detail="MONGODB_URI not configured")
    
    # Try to initialize connection if it wasn't set during startup
    if not client:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"MongoDB client initialization failed: {str(e)}")
    
    try:
        result = await client.admin.command('ping')
        return {
            "status": "ok",
            "handshake": "success",
            "ping": result
        }
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        raise HTTPException(status_code=503, detail=f"MongoDB handshake failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/health/storage")
async def health_storage():
    """Dedicated Vultr Object Storage connection test endpoint"""
    if not VULTR_ENDPOINT or not VULTR_ACCESS_KEY or not VULTR_SECRET_KEY:
        raise HTTPException(
            status_code=500, 
            detail="Vultr Object Storage credentials not configured. Set VULTR_ENDPOINT, VULTR_ACCESS_KEY, and VULTR_SECRET_KEY"
        )
    
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 client not initialized")
    
    try:
        # List all buckets to test connection
        buckets_response = s3_client.list_buckets()
        buckets = [bucket['Name'] for bucket in buckets_response.get('Buckets', [])]
        
        result = {
            "status": "connected",
            "endpoint": VULTR_ENDPOINT,
            "buckets": buckets,
            "configured_bucket": VULTR_BUCKET if VULTR_BUCKET else None
        }
        
        # If a bucket is configured, test access to it
        if VULTR_BUCKET:
            try:
                s3_client.head_bucket(Bucket=VULTR_BUCKET)
                result["bucket_exists"] = True
                result["bucket_accessible"] = True
                
                # Get bucket info
                try:
                    bucket_location = s3_client.get_bucket_location(Bucket=VULTR_BUCKET)
                    result["bucket_location"] = bucket_location.get('LocationConstraint', 'N/A')
                except:
                    pass
                
                # Count objects in bucket
                try:
                    objects = s3_client.list_objects_v2(Bucket=VULTR_BUCKET, MaxKeys=1)
                    result["bucket_has_objects"] = objects.get('KeyCount', 0) > 0
                    result["object_count"] = objects.get('KeyCount', 0)
                except:
                    result["bucket_has_objects"] = False
                    
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == '404':
                    result["bucket_exists"] = False
                    result["error"] = f"Bucket '{VULTR_BUCKET}' not found"
                else:
                    result["bucket_exists"] = True
                    result["bucket_accessible"] = False
                    result["error"] = str(e)
        else:
            result["message"] = "No bucket configured (VULTR_BUCKET not set)"
        
        return result
        
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid Object Storage credentials")
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        raise HTTPException(
            status_code=503, 
            detail=f"Object Storage error ({error_code}): {error_message}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Object Storage error: {str(e)}")


# ============================================================================
# Authentication - User registration and login
# ============================================================================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get the current user from JWT token."""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    token = credentials.credentials
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


@app.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    """Register a new user."""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    # Check if user already exists
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash password and create user
    hashed_password = get_password_hash(user_data.password)
    user_doc = {
        "email": user_data.email,
        "hashed_password": hashed_password,
        "created_at": None  # Will be set by MongoDB if using timestamps
    }
    
    # Add prompt if provided
    if user_data.prompt is not None:
        user_doc["prompt"] = user_data.prompt
    
    try:
        result = await users_collection.insert_one(user_doc)
        user_id = str(result.inserted_id)
        
        # Create access token
        access_token = create_access_token(data={"sub": user_id, "email": user_data.email})
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=user_id,
            email=user_data.email
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@app.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin):
    """Login and get access token."""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    # Find user by email
    user = await users_collection.find_one({"email": user_data.email})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(user_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    user_id = str(user["_id"])
    access_token = create_access_token(data={"sub": user_id, "email": user_data.email})
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        email=user_data.email
    )


@app.get("/auth/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information."""
    return {
        "user_id": str(current_user["_id"]),
        "email": current_user["email"]
    }


# ============================================================================
# User Job Views - Track which jobs a user has seen
# ============================================================================

@app.post("/user-job-views/mark-seen", response_model=UserJobViewResponse)
async def mark_job_as_seen(request: MarkSeenRequest):
    """
    Mark a job as seen for a specific user.
    
    Creates a new record if it doesn't exist, or updates existing record.
    Uses upsert to handle both cases atomically.
    """
    if user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        # Use upsert to create or update the record
        result = await user_job_views_collection.update_one(
            {"user_id": request.user_id, "greenhouse_id": request.greenhouse_id},
            {"$set": {"seen": True}},
            upsert=True
        )
        
        return UserJobViewResponse(
            user_id=request.user_id,
            greenhouse_id=request.greenhouse_id,
            seen=True
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/user-job-views/check")
async def check_job_seen(user_id: str = Query(...), greenhouse_id: str = Query(...)):
    """
    Check if a specific job has been seen by a user.
    
    Returns seen=true if the user has seen the job, false otherwise.
    """
    if user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        doc = await user_job_views_collection.find_one(
            {"user_id": user_id, "greenhouse_id": greenhouse_id}
        )
        
        return {
            "user_id": user_id,
            "greenhouse_id": greenhouse_id,
            "seen": doc.get("seen", False) if doc else False
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.post("/user-job-views/bulk-check")
async def bulk_check_jobs_seen(request: BulkCheckRequest):
    """
    Check multiple jobs at once for a user.
    
    Returns a dictionary mapping greenhouse_id -> seen status.
    Useful for filtering a batch of jobs to only show unseen ones.
    """
    if user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        # Query all matching records for this user and the given greenhouse_ids
        cursor = user_job_views_collection.find({
            "user_id": request.user_id,
            "greenhouse_id": {"$in": request.greenhouse_ids}
        })
        
        # Build a set of seen greenhouse_ids
        seen_ids = set()
        async for doc in cursor:
            if doc.get("seen", False):
                seen_ids.add(doc["greenhouse_id"])
        
        # Build response with all greenhouse_ids
        results = {gid: gid in seen_ids for gid in request.greenhouse_ids}
        
        return {
            "user_id": request.user_id,
            "results": results,
            "seen_count": len(seen_ids),
            "unseen_count": len(request.greenhouse_ids) - len(seen_ids)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/user-job-views/seen-jobs")
async def get_seen_jobs(
    user_id: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0)
):
    """
    Get all jobs that a user has seen.
    
    Returns a paginated list of greenhouse_ids that the user has seen.
    """
    if user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        cursor = user_job_views_collection.find(
            {"user_id": user_id, "seen": True},
            {"greenhouse_id": 1, "_id": 0}
        ).skip(skip).limit(limit)
        
        seen_jobs = []
        async for doc in cursor:
            seen_jobs.append(doc["greenhouse_id"])
        
        # Get total count
        total = await user_job_views_collection.count_documents(
            {"user_id": user_id, "seen": True}
        )
        
        return {
            "user_id": user_id,
            "seen_jobs": seen_jobs,
            "count": len(seen_jobs),
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.delete("/user-job-views/reset")
async def reset_user_job_views(user_id: str = Query(...)):
    """
    Reset all seen jobs for a user (mark all as unseen / delete records).
    
    Useful for allowing users to re-discover jobs they've already seen.
    """
    if user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        result = await user_job_views_collection.delete_many({"user_id": user_id})
        
        return {
            "user_id": user_id,
            "deleted_count": result.deleted_count,
            "message": f"Reset {result.deleted_count} job views for user"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ============================================================================
# Semantic Job Search - Vector search with on-demand video generation
# ============================================================================

async def enqueue_generation_job(
    greenhouse_id: str,
    query_fingerprint: str,
    user_id: str,
    template_id: str
) -> Optional[str]:
    """
    Enqueue a video generation job for a job that doesn't have a video.
    
    Returns the job_id if enqueued, None if skipped (already exists or at limit).
    """
    if generation_jobs_collection is None:
        return None
    
    # Check for existing job with same fingerprint + greenhouse_id
    existing = await generation_jobs_collection.find_one({
        "query_fingerprint": query_fingerprint,
        "greenhouse_id": greenhouse_id,
        "status": {"$nin": ["failed"]}  # Allow retry if previously failed
    })
    if existing:
        print(f"  Skipping generation for {greenhouse_id} - job already exists")
        return None
    
    # Check user's concurrent job limit
    active_count = await generation_jobs_collection.count_documents({
        "user_id": user_id,
        "status": {"$in": ["queued", "running"]}
    })
    if active_count >= MAX_USER_CONCURRENT_JOBS:
        print(f"  Skipping generation for {greenhouse_id} - user at concurrent limit ({active_count}/{MAX_USER_CONCURRENT_JOBS})")
        return None
    
    # Generate job ID and use greenhouse_id as output video ID
    job_id = str(uuid.uuid4())
    output_video_id = str(greenhouse_id)  # video_id = greenhouse_id
    
    # Create generation job document
    job_doc = {
        "job_id": job_id,
        "greenhouse_id": greenhouse_id,
        "template_id": template_id,
        "query_fingerprint": query_fingerprint,
        "user_id": user_id,
        "status": "queued",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "started_at": None,
        "completed_at": None,
        "output_video_id": output_video_id,
        "error": None,
        "retry_count": 0,
        "worker_id": None
    }
    
    try:
        await generation_jobs_collection.insert_one(job_doc)
        print(f"  Enqueued generation job {job_id} for greenhouse_id={greenhouse_id}, template={template_id}")
        return job_id
    except DuplicateKeyError:
        print(f"  Skipping generation for {greenhouse_id} - duplicate key")
        return None


@app.post("/jobs/search", response_model=SearchJobsResponse)
async def search_jobs(request: SearchJobsRequest):
    """
    Search for jobs using semantic similarity with on-demand video generation.
    
    Takes a text prompt and user_id, returns the most relevant jobs that have videos.
    If insufficient videos are available above the similarity threshold, triggers
    on-demand video generation for high-matching jobs that lack videos.
    
    Args:
        text_prompt: Natural language search query (e.g., "Python developer remote")
        user_id: User ID to filter out already-seen jobs
    
    Returns:
        - greenhouse_ids: List of job IDs that have videos (only playable content)
        - generation_triggered: True if new videos are being generated
        - generation_job_ids: IDs of enqueued generation jobs
    """
    if jobs_collection is None or user_job_views_collection is None or videos_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    
    try:
        # Compute query fingerprint for deduplication
        query_fingerprint = compute_query_fingerprint(request.text_prompt)
        print(f"Search: user={request.user_id}, query_fingerprint={query_fingerprint}")
        
        # Step 1: Generate embedding for the text prompt
        try:
            model_name = f"models/{EMBEDDING_MODEL}" if not EMBEDDING_MODEL.startswith("models/") else EMBEDDING_MODEL
            
            embedding_result = genai.embed_content(
                model=model_name,
                content=request.text_prompt,
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIMENSION
            )
            
            if isinstance(embedding_result, dict):
                query_vector = embedding_result.get('embedding', embedding_result.get('values', None))
            else:
                query_vector = getattr(embedding_result, 'embedding', getattr(embedding_result, 'values', None))
            
            if query_vector is None:
                query_vector = embedding_result if isinstance(embedding_result, list) else list(embedding_result)
            
            query_vector = list(query_vector)
            if len(query_vector) != EMBEDDING_DIMENSION:
                raise ValueError(f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSION}, got {len(query_vector)}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to generate embedding: {str(e)}")
        
        # Step 2: Get list of greenhouse_ids the user has already seen
        seen_cursor = user_job_views_collection.find(
            {"user_id": request.user_id, "seen": True},
            {"greenhouse_id": 1, "_id": 0}
        )
        seen_greenhouse_ids = []
        seen_greenhouse_ids_as_ints = []
        async for doc in seen_cursor:
            gh_id = doc["greenhouse_id"]
            seen_greenhouse_ids.append(str(gh_id))
            # Also store as int for MongoDB filter (jobs collection uses int)
            try:
                seen_greenhouse_ids_as_ints.append(int(gh_id))
            except (ValueError, TypeError):
                pass
        
        # Step 3: Vector search for top K jobs (more than TARGET_COUNT to allow filtering)
        print(f"  User has seen {len(seen_greenhouse_ids_as_ints)} jobs: {seen_greenhouse_ids_as_ints[:10]}")  # Debug
        vector_search_filter = {"active": True}
        if seen_greenhouse_ids_as_ints:
            # Use int version for filter since jobs collection stores greenhouse_id as int
            vector_search_filter["greenhouse_id"] = {"$nin": seen_greenhouse_ids_as_ints}
        
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": VECTOR_SEARCH_CANDIDATES,
                    "limit": VECTOR_SEARCH_LIMIT,
                    "filter": vector_search_filter
                }
            },
            {
                "$addFields": {
                    "score": {"$meta": "vectorSearchScore"}
                }
            },
            {
                "$project": {
                    "greenhouse_id": 1,
                    "score": 1,
                    "description": 1,  # Keep for potential generation
                    "_id": 0
                }
            }
        ]
        
        # Execute vector search
        job_results = []
        try:
            async for doc in jobs_collection.aggregate(pipeline):
                if doc.get("greenhouse_id"):
                    job_results.append({
                        "greenhouse_id": doc["greenhouse_id"],  # Keep original type
                        "score": doc.get("score", 0),
                        "description": doc.get("description", "")
                    })
            print(f"  Vector search returned {len(job_results)} jobs")
        except Exception as agg_error:
            error_msg = str(agg_error)
            print(f"  Vector search failed: {error_msg}. Using fallback...")
            
            # Fallback to non-vector search
            fallback_filter = {"active": True}
            if seen_greenhouse_ids_as_ints:
                fallback_filter["greenhouse_id"] = {"$nin": seen_greenhouse_ids_as_ints}
            
            cursor = jobs_collection.find(
                fallback_filter,
                {"greenhouse_id": 1, "description": 1, "_id": 0}
            ).limit(VECTOR_SEARCH_LIMIT)
            
            async for doc in cursor:
                if doc.get("greenhouse_id"):
                    job_results.append({
                        "greenhouse_id": doc["greenhouse_id"],  # Keep original type
                        "score": 0.5,  # Default score for fallback
                        "description": doc.get("description", "")
                    })
        
        if not job_results:
            # If no results found but user has seen videos, reset their seen list and retry
            if seen_greenhouse_ids:
                print(f"  No unseen jobs found, but user has seen {len(seen_greenhouse_ids)} jobs. Resetting seen list...")
                await user_job_views_collection.delete_many({"user_id": request.user_id})
                
                # Retry the vector search without filtering seen jobs
                pipeline = [
                    {
                        "$vectorSearch": {
                            "index": "vector_index",
                            "path": "embedding",
                            "queryVector": query_vector,
                            "numCandidates": VECTOR_SEARCH_CANDIDATES,
                            "limit": VECTOR_SEARCH_LIMIT,
                            "filter": {"active": True}  # No seen filter this time
                        }
                    },
                    {
                        "$addFields": {
                            "score": {"$meta": "vectorSearchScore"}
                        }
                    },
                    {
                        "$project": {
                            "greenhouse_id": 1,
                            "score": 1,
                            "description": 1,
                            "_id": 0
                        }
                    }
                ]
                
                job_results = []
                async for doc in jobs_collection.aggregate(pipeline):
                    if doc.get("greenhouse_id"):
                        job_results.append({
                            "greenhouse_id": doc["greenhouse_id"],
                            "score": doc.get("score", 0),
                            "description": doc.get("description", "")
                        })
                print(f"  After reset: found {len(job_results)} jobs")
            
            if not job_results:
                print("  No jobs found even after reset")
                return SearchJobsResponse(
                    user_id=request.user_id,
                    greenhouse_ids=[],
                    count=0,
                    generation_triggered=False,
                    generation_job_ids=[]
                )
        
        # Step 4: Check which jobs have videos (video_id = greenhouse_id)
        greenhouse_ids = [j["greenhouse_id"] for j in job_results]
        videos_cursor = videos_collection.find(
            {"video_id": {"$in": greenhouse_ids}, "status": "ready"},
            {"video_id": 1, "_id": 0}
        )
        jobs_with_videos = set()
        async for doc in videos_cursor:
            jobs_with_videos.add(doc["video_id"])  # video_id = greenhouse_id
        
        print(f"  {len(jobs_with_videos)} jobs have videos out of {len(job_results)} searched")
        print(f"  Jobs with videos: {list(jobs_with_videos)}")
        
        # Step 5: Split into categories
        jobs_with_videos_above_threshold = []
        jobs_with_videos_below_threshold = []
        jobs_without_videos_above_threshold = []
        
        for job in job_results:
            has_video = job["greenhouse_id"] in jobs_with_videos
            above_threshold = job["score"] >= SIMILARITY_THRESHOLD
            
            if has_video:
                if above_threshold:
                    jobs_with_videos_above_threshold.append(job)
                else:
                    jobs_with_videos_below_threshold.append(job)
            else:
                if above_threshold:
                    jobs_without_videos_above_threshold.append(job)
        
        print(f"  Above threshold with videos: {len(jobs_with_videos_above_threshold)}")
        print(f"  Below threshold with videos: {len(jobs_with_videos_below_threshold)}")
        print(f"  Above threshold without videos: {len(jobs_without_videos_above_threshold)}")
        
        # Combine available videos: above threshold first, then below threshold
        available_with_videos = jobs_with_videos_above_threshold + jobs_with_videos_below_threshold
        
        # Step 5.5: Reset if no videos available but user has seen videos
        if len(available_with_videos) == 0 and len(seen_greenhouse_ids_as_ints) > 0:
            print(f"  No videos available but user has seen {len(seen_greenhouse_ids_as_ints)} jobs. Resetting...")
            await user_job_views_collection.delete_many({"user_id": request.user_id})
            
            # Get ALL available videos (not just from current search results)
            all_videos_cursor = videos_collection.find(
                {"status": "ready"},
                {"video_id": 1, "_id": 0}
            ).limit(TARGET_COUNT)
            
            all_available_video_ids = []
            async for doc in all_videos_cursor:
                all_available_video_ids.append(doc["video_id"])
            
            print(f"  After reset: {len(all_available_video_ids)} total videos available")
            
            # Return these videos directly (they're below threshold but better than nothing)
            results_to_return = [str(vid) for vid in all_available_video_ids[:TARGET_COUNT]]
            
            # Mark them as seen immediately
            for greenhouse_id in results_to_return:
                try:
                    gh_id_to_store = int(greenhouse_id)
                except (ValueError, TypeError):
                    gh_id_to_store = greenhouse_id
                
                await user_job_views_collection.update_one(
                    {"user_id": request.user_id, "greenhouse_id": gh_id_to_store},
                    {"$set": {"seen": True}},
                    upsert=True
                )
            
            print(f"  Returning {len(results_to_return)} videos after reset")
            
            return SearchJobsResponse(
                user_id=request.user_id,
                greenhouse_ids=results_to_return,
                count=len(results_to_return),
                generation_triggered=False,
                generation_job_ids=[]
            )
        
        # Step 6: Determine what to return and whether to trigger generation
        generation_triggered = False
        generation_job_ids = []
        
        # If we have enough above threshold, no generation needed
        if len(jobs_with_videos_above_threshold) >= TARGET_COUNT:
            results_to_return = [str(j["greenhouse_id"]) for j in jobs_with_videos_above_threshold[:TARGET_COUNT]]
            print(f"  Enough videos above threshold, returning {len(results_to_return)}")
        else:
            # Return best available (even if below threshold)
            results_to_return = [str(j["greenhouse_id"]) for j in available_with_videos[:TARGET_COUNT]]
            print(f"  Returning {len(results_to_return)} available videos")
            
            # Calculate deficit and trigger generation
            deficit = TARGET_COUNT - len(jobs_with_videos_above_threshold)
            jobs_to_generate = jobs_without_videos_above_threshold[:min(deficit, MAX_GENERATE_PER_REQUEST)]
            
            if jobs_to_generate:
                print(f"  Triggering generation for {len(jobs_to_generate)} jobs (deficit={deficit})")
                generation_triggered = True
                
                for job in jobs_to_generate:
                    # Select random template
                    template_id = random.choice(VIDEO_TEMPLATES)
                    
                    job_id = await enqueue_generation_job(
                        greenhouse_id=job["greenhouse_id"],
                        query_fingerprint=query_fingerprint,
                        user_id=request.user_id,
                        template_id=template_id
                    )
                    if job_id:
                        generation_job_ids.append(job_id)
        
        # Step 7: Mark the returned jobs as seen
        for greenhouse_id in results_to_return:
            # Store as int to match jobs collection type
            try:
                gh_id_to_store = int(greenhouse_id)
            except (ValueError, TypeError):
                gh_id_to_store = greenhouse_id
            
            await user_job_views_collection.update_one(
                {"user_id": request.user_id, "greenhouse_id": gh_id_to_store},
                {"$set": {"seen": True}},
                upsert=True
            )
        
        print(f"  Final response: {len(results_to_return)} jobs, generation_triggered={generation_triggered}")
        
        return SearchJobsResponse(
            user_id=request.user_id,
            greenhouse_ids=results_to_return,
            count=len(results_to_return),
            generation_triggered=generation_triggered,
            generation_job_ids=generation_job_ids
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


# ============================================================================
# Admin Endpoints - Generation Job Management
# ============================================================================

@app.get("/admin/generation-jobs")
async def list_generation_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0)
):
    """
    List generation jobs with optional status filter.
    
    Args:
        status: Filter by status (queued, running, uploaded, indexed, ready, failed)
        limit: Maximum number of jobs to return (default: 50)
        skip: Number of jobs to skip for pagination
    """
    if generation_jobs_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        query = {}
        if status_filter:
            query["status"] = status_filter
        
        cursor = generation_jobs_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        
        jobs = []
        async for doc in cursor:
            jobs.append({
                "job_id": doc.get("job_id"),
                "greenhouse_id": doc.get("greenhouse_id"),
                "template_id": doc.get("template_id"),
                "status": doc.get("status"),
                "user_id": doc.get("user_id"),
                "query_fingerprint": doc.get("query_fingerprint"),
                "output_video_id": doc.get("output_video_id"),
                "error": doc.get("error"),
                "retry_count": doc.get("retry_count", 0),
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                "started_at": doc.get("started_at").isoformat() if doc.get("started_at") else None,
                "completed_at": doc.get("completed_at").isoformat() if doc.get("completed_at") else None
            })
        
        total = await generation_jobs_collection.count_documents(query)
        
        return {
            "jobs": jobs,
            "count": len(jobs),
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/admin/generation-jobs/stats")
async def get_generation_jobs_stats():
    """
    Get statistics on generation jobs and videos.
    """
    if generation_jobs_collection is None or videos_collection is None or jobs_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        # Count generation jobs by status
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_counts = {}
        async for doc in generation_jobs_collection.aggregate(pipeline):
            status_counts[doc["_id"]] = doc["count"]
        
        # Count videos
        total_videos = await videos_collection.count_documents({})
        ready_videos = await videos_collection.count_documents({"status": "ready"})
        
        # Count jobs with and without videos
        total_jobs = await jobs_collection.count_documents({"active": True})
        
        # Get greenhouse_ids that have videos
        video_greenhouse_ids = await videos_collection.distinct("greenhouse_id", {"status": "ready"})
        jobs_with_videos = len(video_greenhouse_ids)
        
        return {
            "generation_jobs": {
                "queued": status_counts.get("queued", 0),
                "running": status_counts.get("running", 0),
                "uploaded": status_counts.get("uploaded", 0),
                "indexed": status_counts.get("indexed", 0),
                "ready": status_counts.get("ready", 0),
                "failed": status_counts.get("failed", 0),
                "total": sum(status_counts.values())
            },
            "videos": {
                "total": total_videos,
                "ready": ready_videos
            },
            "jobs": {
                "total_active": total_jobs,
                "with_videos": jobs_with_videos,
                "without_videos": total_jobs - jobs_with_videos
            },
            "config": {
                "similarity_threshold": SIMILARITY_THRESHOLD,
                "target_count": TARGET_COUNT,
                "max_generate_per_request": MAX_GENERATE_PER_REQUEST,
                "max_user_concurrent_jobs": MAX_USER_CONCURRENT_JOBS
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/admin/generation-jobs/{job_id}")
async def get_generation_job(job_id: str):
    """
    Get details of a specific generation job.
    """
    if generation_jobs_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        doc = await generation_jobs_collection.find_one({"job_id": job_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Generation job {job_id} not found")
        
        return {
            "job_id": doc.get("job_id"),
            "greenhouse_id": doc.get("greenhouse_id"),
            "template_id": doc.get("template_id"),
            "status": doc.get("status"),
            "user_id": doc.get("user_id"),
            "query_fingerprint": doc.get("query_fingerprint"),
            "output_video_id": doc.get("output_video_id"),
            "error": doc.get("error"),
            "retry_count": doc.get("retry_count", 0),
            "worker_id": doc.get("worker_id"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
            "started_at": doc.get("started_at").isoformat() if doc.get("started_at") else None,
            "completed_at": doc.get("completed_at").isoformat() if doc.get("completed_at") else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.post("/admin/generation-jobs/{job_id}/retry")
async def retry_generation_job(job_id: str):
    """
    Force retry a failed generation job by resetting its status to queued.
    """
    if generation_jobs_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    try:
        result = await generation_jobs_collection.update_one(
            {"job_id": job_id, "status": "failed"},
            {
                "$set": {
                    "status": "queued",
                    "updated_at": datetime.utcnow(),
                    "error": None,
                    "worker_id": None,
                    "started_at": None
                },
                "$inc": {"retry_count": 1}
            }
        )
        
        if result.matched_count == 0:
            # Check if job exists
            job = await generation_jobs_collection.find_one({"job_id": job_id})
            if not job:
                raise HTTPException(status_code=404, detail=f"Generation job {job_id} not found")
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Job is not in failed status (current: {job.get('status')})"
                )
        
        return {
            "message": f"Job {job_id} queued for retry",
            "job_id": job_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/videos/list")
async def list_videos(limit: int = Query(default=4, ge=1, le=100)):
    """
    List video files from Vultr Object Storage.
    
    Args:
        limit: Maximum number of videos to return (default: 4, max: 100)
    
    Returns:
        JSON with list of video URLs
    """
    if not s3_client:
        raise HTTPException(status_code=503, detail="Object Storage not configured or unavailable")
    
    if not VULTR_BUCKET:
        raise HTTPException(status_code=500, detail="VULTR_BUCKET not configured")
    
    try:
        # List objects in the bucket
        response = s3_client.list_objects_v2(
            Bucket=VULTR_BUCKET,
            MaxKeys=limit
        )
        
        if 'Contents' not in response:
            return {
                "videos": [],
                "count": 0
            }
        
        # Filter for video files and construct URLs
        video_extensions = {'.mp4', '.mov', '.avi', '.webm', '.m4v'}
        videos = []
        
        for obj in response['Contents']:
            key = obj['Key']
            # Check if it's a video file
            if any(key.lower().endswith(ext) for ext in video_extensions):
                # Construct public URL
                video_url = f"{VULTR_ENDPOINT}/{VULTR_BUCKET}/{key}"
                videos.append({
                    "key": key,
                    "url": video_url,
                    "size": obj.get('Size', 0),
                    "last_modified": obj.get('LastModified').isoformat() if obj.get('LastModified') else None
                })
        
        return {
            "videos": videos[:limit],
            "count": len(videos[:limit])
        }
        
    except ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to list videos from Object Storage: {str(e)}"
        )

