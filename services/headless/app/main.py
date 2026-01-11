"""FastAPI application for the headless service."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.db import close_database, cleanup_stuck_analyzing, expire_stale_applications
from app.fetching.scraper import run_scraper
from app.routes.applications import router as applications_router

# Load environment variables
# Priority: 1) Already set env vars (Docker Compose), 2) Local .env, 3) Project root .env
local_env = Path(__file__).parent.parent / ".env"  # services/headless/.env
project_env = Path(__file__).parent.parent.parent.parent / ".env"  # DeltaHacks12/.env

if local_env.exists():
    load_dotenv(local_env)
elif project_env.exists():
    load_dotenv(project_env)
# If neither exists, rely on environment variables (Docker Compose sets them)

# Load environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "app")


async def run_cleanup_loop():
    """Background task to cleanup expired and stuck applications."""
    while True:
        try:
            # Expire pending_review applications past their TTL
            expired_count = await expire_stale_applications()
            if expired_count > 0:
                print(f"Expired {expired_count} stale applications")

            # Cleanup stuck analyzing applications (> 10 min)
            stuck_count = await cleanup_stuck_analyzing()
            if stuck_count > 0:
                print(f"Cleaned up {stuck_count} stuck applications")

        except Exception as e:
            print(f"Cleanup task error: {e}")

        # Run every 60 seconds
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup: run the scraper and cleanup task
    print("Starting up headless service...")

    # Run scraper in background task so it doesn't block health checks
    scraper_task = asyncio.create_task(run_scraper())

    # Run cleanup task for expired applications
    cleanup_task = asyncio.create_task(run_cleanup_loop())

    yield

    # Shutdown: cancel background tasks and close database
    for task in [scraper_task, cleanup_task]:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await close_database()
    print("Headless service shut down")


app = FastAPI(
    title="Headless Service",
    description="Job application automation service",
    version="1.0.0",
    lifespan=lifespan
)

# Include routers
app.include_router(applications_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
