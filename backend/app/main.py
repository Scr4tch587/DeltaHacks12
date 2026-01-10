import os
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

app = FastAPI()

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")

# Vultr Object Storage (S3-compatible) variables
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "")

# MongoDB client (will be initialized on startup)
client = None
db = None

# S3 client for Vultr Object Storage
s3_client = None


@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection and S3 client on startup"""
    global client, db, s3_client
    
    # Initialize MongoDB
    if MONGODB_URI:
        try:
            client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[MONGODB_DB]
            # Test the connection
            await client.admin.command('ping')
            print(f"✓ Connected to MongoDB Atlas (database: {MONGODB_DB})")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"✗ MongoDB connection failed: {e}")
            client = None
            db = None
    else:
        print("⚠ MONGODB_URI not set - skipping MongoDB connection")
    
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
    """Dedicated MongoDB connection test endpoint"""
    if not MONGODB_URI:
        raise HTTPException(status_code=500, detail="MONGODB_URI not configured")
    
    if not client:
        raise HTTPException(status_code=503, detail="MongoDB client not initialized")
    
    try:
        # Ping the database
        result = await client.admin.command('ping')
        # Get database info
        db_info = await db.command('dbStats')
        
        return {
            "status": "connected",
            "mongodb_uri_set": bool(MONGODB_URI),
            "database": MONGODB_DB,
            "ping": result,
            "database_stats": {
                "name": db_info.get("db", MONGODB_DB),
                "collections": db_info.get("collections", 0),
                "data_size": db_info.get("dataSize", 0)
            }
        }
    except ConnectionFailure as e:
        raise HTTPException(status_code=503, detail=f"MongoDB connection failed: {str(e)}")
    except ServerSelectionTimeoutError as e:
        raise HTTPException(status_code=503, detail=f"MongoDB server selection timeout: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MongoDB error: {str(e)}")


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
