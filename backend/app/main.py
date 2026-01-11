import os
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId
from pydantic import BaseModel, EmailStr
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import google.generativeai as genai
from app.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# MongoDB client (will be initialized on startup)
client = None
db = None
users_collection = None
user_job_views_collection = None
jobs_collection = None

# Security
security = HTTPBearer()

# S3 client for Vultr Object Storage
s3_client = None


# Pydantic models for request/response
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


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


@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection, S3 client, and Gemini API on startup"""
    global client, db, s3_client, users_collection, user_job_views_collection, jobs_collection
    
    # Initialize MongoDB
    if MONGODB_URI:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
            # Test the connection
            await client.admin.command('ping')
            print(f"✓ Connected to MongoDB Atlas (database: {MONGODB_DB})")
            
            # Initialize users collection and create indexes
            users_collection = db.users
            await users_collection.create_index("username", unique=True)
            await users_collection.create_index("email", unique=True)
            print("✓ users collection initialized with indexes")
            
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
# Authentication - User registration, login, and token verification
# ============================================================================

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Get current user from JWT token"""
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    # Convert string user_id back to ObjectId
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user ID format")
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


@app.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserRegister):
    """Register a new user"""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    # Check if username already exists
    existing_user = await users_collection.find_one({"username": user_data.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Check if email already exists
    existing_email = await users_collection.find_one({"email": user_data.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash password
    hashed_password = get_password_hash(user_data.password)
    
    # Create user document
    user_doc = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hashed_password,
        "created_at": datetime.utcnow(),
    }
    
    # Insert user
    result = await users_collection.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    # Create access token
    access_token = create_access_token(data={"sub": user_id})
    
    # Return token and user info
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user_id,
            username=user_data.username,
            email=user_data.email,
            created_at=user_doc["created_at"],
        ),
    )


@app.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin):
    """Login with username and password"""
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Database not connected")
    
    # Find user by username
    user = await users_collection.find_one({"username": user_data.username})
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    # Verify password
    if not verify_password(user_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    # Create access token
    user_id = str(user["_id"])
    access_token = create_access_token(data={"sub": user_id})
    
    # Return token and user info
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user_id,
            username=user["username"],
            email=user["email"],
            created_at=user.get("created_at"),
        ),
    )


@app.get("/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(
        id=str(current_user["_id"]),
        username=current_user["username"],
        email=current_user["email"],
        created_at=current_user.get("created_at"),
    )


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
# Semantic Job Search - Vector search with unseen jobs filtering
# ============================================================================

@app.post("/jobs/search", response_model=SearchJobsResponse)
async def search_jobs(request: SearchJobsRequest):
    """
    Search for jobs using semantic similarity.
    
    Takes a text prompt and user_id, returns the 5 most relevant jobs the user hasn't seen yet.
    Uses MongoDB vector search with Gemini embeddings.
    Automatically marks the returned jobs as seen.
    
    Args:
        text_prompt: Natural language search query (e.g., "Python developer remote")
        user_id: User ID to filter out already-seen jobs
    
    Returns:
        List of 5 most relevant greenhouse_ids (marked as seen)
    """
    if jobs_collection is None or user_job_views_collection is None:
        raise HTTPException(status_code=503, detail="MongoDB not connected")
    
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    
    try:
        # Step 1: Generate embedding for the text prompt
        try:
            # Use the google-generativeai SDK to generate embeddings
            # Note: For text-embedding-004, the model name should include "models/" prefix
            model_name = f"models/{EMBEDDING_MODEL}" if not EMBEDDING_MODEL.startswith("models/") else EMBEDDING_MODEL
            
            embedding_result = genai.embed_content(
                model=model_name,
                content=request.text_prompt,
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIMENSION
            )
            
            # Extract embedding - the result structure may vary by SDK version
            # Common formats: dict with 'embedding' key, or object with .embedding attribute
            if isinstance(embedding_result, dict):
                query_vector = embedding_result.get('embedding', embedding_result.get('values', None))
            else:
                query_vector = getattr(embedding_result, 'embedding', getattr(embedding_result, 'values', None))
            
            if query_vector is None:
                # Fallback: if result is directly a list
                query_vector = embedding_result if isinstance(embedding_result, list) else list(embedding_result)
            
            # Convert to list if needed and validate
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
        async for doc in seen_cursor:
            seen_greenhouse_ids.append(str(doc["greenhouse_id"]))  # Ensure string format
        
        # Quick check: verify jobs exist in database
        jobs_count = await jobs_collection.count_documents({"active": True})
        if jobs_count == 0:
            raise HTTPException(
                status_code=404,
                detail="No active jobs found in database"
            )
        
        # Step 3: Build vector search pipeline
        # Filter: active=true AND greenhouse_id NOT IN seen_greenhouse_ids
        vector_search_filter = {"active": True}
        if seen_greenhouse_ids:
            vector_search_filter["greenhouse_id"] = {"$nin": seen_greenhouse_ids}
        
        # MongoDB vector search aggregation pipeline
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "jobs_semantic_search",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": 50,  # Search more candidates to ensure we get 5 after filtering
                    "limit": 5,
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
                    "_id": 0
                }
            },
            {
                "$limit": 5
            }
        ]
        
        # Step 4: Execute vector search
        results = []
        vector_search_worked = False
        try:
            async for doc in jobs_collection.aggregate(pipeline):
                if doc.get("greenhouse_id"):
                    results.append(str(doc["greenhouse_id"]))  # Ensure string format
                    vector_search_worked = True
        except Exception as agg_error:
            # If vector search fails (e.g., index doesn't exist), try a simpler approach
            error_msg = str(agg_error)
            print(f"Vector search failed: {error_msg}. Attempting fallback query...")
            
            # Check if it's an index error
            if "index" in error_msg.lower() or "vector" in error_msg.lower():
                # Fallback to non-vector search
                vector_search_worked = False
        
        # Fallback: If vector search returned 0 results but jobs exist, use regular query
        # This handles the case where the vector search index doesn't exist yet
        if not results and jobs_count > 0:
            print("Vector search returned 0 results. Using fallback non-vector query...")
            fallback_filter = {"active": True}
            if seen_greenhouse_ids:
                fallback_filter["greenhouse_id"] = {"$nin": seen_greenhouse_ids}
            
            # Just get first 5 jobs matching criteria (without vector search)
            cursor = jobs_collection.find(fallback_filter, {"greenhouse_id": 1, "_id": 0}).limit(5)
            async for doc in cursor:
                if doc.get("greenhouse_id"):
                    results.append(str(doc["greenhouse_id"]))
        
        if not results:
            return SearchJobsResponse(
                user_id=request.user_id,
                greenhouse_ids=[],
                count=0
            )
        
        # Step 5: Mark the returned jobs as seen
        for greenhouse_id in results:
            await user_job_views_collection.update_one(
                {"user_id": request.user_id, "greenhouse_id": greenhouse_id},
                {"$set": {"seen": True}},
                upsert=True
            )
        
        return SearchJobsResponse(
            user_id=request.user_id,
            greenhouse_ids=results,
            count=len(results)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


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

