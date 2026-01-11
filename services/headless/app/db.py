"""
MongoDB connection and job upsert functions.
"""

import os
import certifi
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# Global client and database references
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def get_database() -> AsyncIOMotorDatabase:
    """Get the MongoDB database instance, creating connection if needed."""
    global _client, _db

    if _db is not None:
        return _db

    mongodb_uri = os.getenv("MONGODB_URI", "")
    mongodb_db = os.getenv("MONGODB_DB", "app")

    if not mongodb_uri:
        raise ValueError("MONGODB_URI environment variable is required")

    # Use certifi's CA bundle for SSL verification
    _client = AsyncIOMotorClient(
        mongodb_uri,
        tlsCAFile=certifi.where()
    )
    _db = _client[mongodb_db]

    return _db


async def close_database() -> None:
    """Close the MongoDB connection."""
    global _client, _db

    if _client is not None:
        _client.close()
        _client = None
        _db = None


async def mark_missing_jobs_as_expired(company_token: str, active_job_ids: list[int]) -> int:
    """
    Mark jobs as expired (active=False) if they are not in the active_job_ids list.

    Args:
        company_token: The company identifier.
        active_job_ids: List of job IDs that are currently active.

    Returns:
        Number of jobs marked as expired.
    """
    db = await get_database()
    collection = db.jobs

    try:
        result = await collection.update_many(
            {
                "company_token": company_token,
                "greenhouse_id": {"$nin": active_job_ids},
                "active": {"$ne": False}  # Only update if not already marked expired
            },
            {"$set": {"active": False, "scraped_at": datetime.utcnow()}}
        )
        return result.modified_count
    except Exception as e:
        print(f"Error marking expired jobs for {company_token}: {e}")
        return 0


async def upsert_job(job_doc: dict[str, Any]) -> bool:
    """
    Upsert a job document into the jobs collection.

    Uses greenhouse_id as the unique key to avoid duplicates on restart.

    Args:
        job_doc: Job document with all required fields including embedding

    Returns:
        True if document was inserted/updated, False on error
    """
    db = await get_database()
    collection = db.jobs

    # Add scraped_at timestamp
    job_doc["scraped_at"] = datetime.utcnow()

    try:
        result = await collection.update_one(
            {"greenhouse_id": job_doc["greenhouse_id"]},
            {"$set": job_doc},
            upsert=True,
        )
        return result.acknowledged
    except Exception as e:
        print(f"Error upserting job {job_doc.get('greenhouse_id')}: {e}")
        return False


async def get_job_count() -> int:
    """Get total number of jobs in the collection."""
    db = await get_database()
    return await db.jobs.count_documents({})


async def ensure_indexes() -> None:
    """Create necessary indexes on the jobs collection."""
    db = await get_database()
    collection = db.jobs

    # Unique index on greenhouse_id
    await collection.create_index("greenhouse_id", unique=True)

    # Index on company_token for filtering
    await collection.create_index("company_token")

    # Index on updated_at for sorting
    await collection.create_index("updated_at")

    print("MongoDB indexes ensured on jobs collection")
    
    await ensure_user_indexes()


async def ensure_user_indexes() -> None:
    """Create necessary indexes on the users collection."""
    db = await get_database()
    collection = db.users
    
    # Unique index on email
    await collection.create_index("email", unique=True)
    
    print("MongoDB indexes ensured on users collection")


async def upsert_user(user_doc: dict[str, Any]) -> bool:
    """
    Upsert a user document into the users collection.

    Uses email as the unique key.

    Args:
        user_doc: User document with required fields (must include email)

    Returns:
        True if document was inserted/updated, False on error
    """
    if "email" not in user_doc:
        print("Error: User document missing email")
        return False
        
    db = await get_database()
    collection = db.users

    # Add updated_at timestamp
    user_doc["updated_at"] = datetime.utcnow()

    try:
        result = await collection.update_one(
            {"email": user_doc["email"]},
            {"$set": user_doc},
            upsert=True,
        )
        return result.acknowledged
    except Exception as e:
        print(f"Error upserting user {user_doc.get('email')}: {e}")
        return False


async def get_user(email: str) -> dict[str, Any] | None:
    """
    Get a user by email.

    Args:
        email: User's email address

    Returns:
        User document or None if not found
    """
    db = await get_database()
    collection = db.users
    return await collection.find_one({"email": email})
