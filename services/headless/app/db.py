"""
MongoDB connection and database functions.
"""

import os
import certifi
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

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
    # LOCAL MODE: Skip cloud writes
    print(f"[LOCAL MODE] Would mark expired jobs for {company_token} (skipped)")
    return 0
    # db = await get_database()
    # collection = db.jobs
    #
    # try:
    #     result = await collection.update_many(
    #         {
    #             "company_token": company_token,
    #             "greenhouse_id": {"$nin": active_job_ids},
    #             "active": {"$ne": False}  # Only update if not already marked expired
    #         },
    #         {"$set": {"active": False, "scraped_at": datetime.utcnow()}}
    #     )
    #     return result.modified_count
    # except Exception as e:
    #     print(f"Error marking expired jobs for {company_token}: {e}")
    #     return 0


async def upsert_job(job_doc: dict[str, Any]) -> bool:
    """
    Upsert a job document into the jobs collection.

    Uses greenhouse_id as the unique key to avoid duplicates on restart.

    Args:
        job_doc: Job document with all required fields including embedding

    Returns:
        True if document was inserted/updated, False on error
    """
    # LOCAL MODE: Skip cloud writes
    print(f"[LOCAL MODE] Would upsert job {job_doc.get('greenhouse_id')}: {job_doc.get('title', 'Unknown')} (skipped)")
    return True
    # db = await get_database()
    # collection = db.jobs
    #
    # # Add scraped_at timestamp
    # job_doc["scraped_at"] = datetime.utcnow()
    #
    # try:
    #     result = await collection.update_one(
    #         {"greenhouse_id": job_doc["greenhouse_id"]},
    #         {"$set": job_doc},
    #         upsert=True,
    #     )
    #     return result.acknowledged
    # except Exception as e:
    #     print(f"Error upserting job {job_doc.get('greenhouse_id')}: {e}")
    #     return False


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
    await ensure_application_indexes()


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


async def get_user(email_or_id: str) -> dict[str, Any] | None:
    """
    Get a user by email or MongoDB ObjectId.

    Args:
        email_or_id: User's email address or MongoDB ObjectId string

    Returns:
        User document or None if not found
    """
    db = await get_database()
    collection = db.users
    
    # Try to parse as ObjectId first
    try:
        object_id = ObjectId(email_or_id)
        user = await collection.find_one({"_id": object_id})
        if user:
            return user
    except Exception:
        # Not a valid ObjectId, continue to email lookup
        pass
    
    # Fall back to email lookup
    return await collection.find_one({"email": email_or_id})


# ============ Application Functions ============


async def ensure_application_indexes() -> None:
    """Create necessary indexes on the applications collection."""
    db = await get_database()
    collection = db.applications

    await collection.create_index("user_id")
    await collection.create_index("status")
    await collection.create_index("expires_at")

    # Unique constraint: one active application per user per job
    await collection.create_index(
        [("user_id", 1), ("job_id", 1)],
        unique=True,
        partialFilterExpression={
            "status": {"$in": ["analyzing", "pending_review", "submitting"]}
        }
    )

    print("MongoDB indexes ensured on applications collection")


async def create_application(app_doc: dict[str, Any]) -> str:
    """
    Create a new application document.

    Args:
        app_doc: Application document (without _id)

    Returns:
        String ID of created document

    Raises:
        Exception if insert fails (e.g., duplicate)
    """
    db = await get_database()
    collection = db.applications

    app_doc["created_at"] = datetime.utcnow()
    app_doc["updated_at"] = datetime.utcnow()

    result = await collection.insert_one(app_doc)
    return str(result.inserted_id)


async def get_application(application_id: str) -> dict[str, Any] | None:
    """
    Get an application by ID.

    Args:
        application_id: String ObjectId

    Returns:
        Application document or None
    """
    db = await get_database()
    collection = db.applications

    try:
        obj_id = ObjectId(application_id)
    except Exception:
        return None

    doc = await collection.find_one({"_id": obj_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def get_application_by_user_and_job(
    user_id: str, job_id: str, active_only: bool = True
) -> dict[str, Any] | None:
    """
    Get an application by user and job ID.

    Args:
        user_id: User's email
        job_id: Job identifier
        active_only: If True, only return non-terminal states

    Returns:
        Application document or None
    """
    db = await get_database()
    collection = db.applications

    query: dict[str, Any] = {"user_id": user_id, "job_id": job_id}
    if active_only:
        query["status"] = {"$in": ["analyzing", "pending_review", "submitting"]}

    doc = await collection.find_one(query, sort=[("created_at", -1)])
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def update_application(
    application_id: str, updates: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Update an application document.

    Args:
        application_id: String ObjectId
        updates: Fields to update

    Returns:
        Updated document or None if not found
    """
    db = await get_database()
    collection = db.applications

    try:
        obj_id = ObjectId(application_id)
    except Exception:
        return None

    updates["updated_at"] = datetime.utcnow()

    doc = await collection.find_one_and_update(
        {"_id": obj_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER
    )
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def transition_application_state(
    application_id: str,
    from_status: str,
    to_status: str,
    additional_updates: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """
    Atomically transition application from one state to another.

    This prevents race conditions like double-submission.

    Args:
        application_id: String ObjectId
        from_status: Required current status
        to_status: New status to set
        additional_updates: Other fields to update

    Returns:
        Updated document if transition succeeded, None if state mismatch
    """
    db = await get_database()
    collection = db.applications

    try:
        obj_id = ObjectId(application_id)
    except Exception:
        return None

    updates = {"status": to_status, "updated_at": datetime.utcnow()}
    if additional_updates:
        updates.update(additional_updates)

    doc = await collection.find_one_and_update(
        {"_id": obj_id, "status": from_status},
        {"$set": updates},
        return_document=ReturnDocument.AFTER
    )
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def expire_stale_applications() -> int:
    """
    Mark expired applications (pending_review past expires_at).

    Returns:
        Number of applications expired
    """
    db = await get_database()
    collection = db.applications

    now = datetime.utcnow()

    result = await collection.update_many(
        {
            "status": "pending_review",
            "expires_at": {"$lt": now}
        },
        {"$set": {"status": "expired", "updated_at": now}}
    )

    return result.modified_count


async def cleanup_stuck_analyzing() -> int:
    """
    Clean up applications stuck in ANALYZING state for too long (>10 min).

    Returns:
        Number of applications cleaned up
    """
    db = await get_database()
    collection = db.applications

    cutoff = datetime.utcnow() - timedelta(minutes=10)

    result = await collection.update_many(
        {
            "status": "analyzing",
            "created_at": {"$lt": cutoff}
        },
        {"$set": {"status": "failed", "error": "Analysis timed out", "updated_at": datetime.utcnow()}}
    )

    return result.modified_count


async def list_user_applications(
    user_id: str,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """
    List applications for a user.

    Args:
        user_id: User's email
        status: Optional status filter
        limit: Max results
        offset: Skip count

    Returns:
        Tuple of (applications list, total count)
    """
    db = await get_database()
    collection = db.applications

    query: dict[str, Any] = {"user_id": user_id}
    if status:
        query["status"] = status

    total = await collection.count_documents(query)
    cursor = collection.find(query).sort("created_at", -1).skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)

    for doc in docs:
        doc["_id"] = str(doc["_id"])

    return docs, total


# ============ User Cache Functions ============


async def update_user_cached_responses(
    user_id: str,
    standard_updates: dict[str, str] | None = None,
    custom_updates: dict[str, dict[str, Any]] | None = None
) -> bool:
    """
    Update a user's cached form responses.

    Args:
        user_id: User's email
        standard_updates: Standard field key -> value mappings
        custom_updates: Custom question hash -> answer data

    Returns:
        True if updated successfully
    """
    db = await get_database()
    collection = db.users

    set_updates: dict[str, Any] = {"updated_at": datetime.utcnow()}

    if standard_updates:
        for key, value in standard_updates.items():
            set_updates[f"cached_responses.standard.{key}"] = value

    if custom_updates:
        for question_hash, answer_data in custom_updates.items():
            set_updates[f"cached_responses.custom.{question_hash}"] = answer_data

    try:
        result = await collection.update_one(
            {"email": user_id},
            {"$set": set_updates}
        )
        return result.modified_count > 0 or result.matched_count > 0
    except Exception as e:
        print(f"Error updating cached responses for {user_id}: {e}")
        return False


async def get_user_cached_responses(user_id: str) -> dict[str, Any]:
    """
    Get a user's cached form responses.

    Args:
        user_id: User's email

    Returns:
        Cached responses dict with 'standard' and 'custom' keys
    """
    user = await get_user(user_id)
    if not user:
        return {"standard": {}, "custom": {}}

    return user.get("cached_responses", {"standard": {}, "custom": {}})


async def get_job(job_id: str) -> dict[str, Any] | None:
    """
    Get a job by greenhouse_id or ObjectId.

    Args:
        job_id: greenhouse_id (int as string) or ObjectId string

    Returns:
        Job document or None
    """
    db = await get_database()
    collection = db.jobs

    # Try as greenhouse_id first (numeric)
    try:
        greenhouse_id = int(job_id)
        doc = await collection.find_one({"greenhouse_id": greenhouse_id})
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
    except ValueError:
        pass

    # Try as ObjectId
    try:
        obj_id = ObjectId(job_id)
        doc = await collection.find_one({"_id": obj_id})
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
    except Exception:
        pass

    return None
