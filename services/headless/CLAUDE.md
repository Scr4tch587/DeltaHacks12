# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **headless service** for DeltaHacks12 (JobReels) - an autonomous job application platform. It scrapes job listings from Greenhouse.io, generates embeddings, and automatically fills out job applications using Playwright browser automation and AI.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run the service (starts scraper in background)
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Manual debugging - launches visible browser for testing application flow
python manual_debug_greenhouse.py

# Run tests
pytest tests/

# Docker build and run
docker compose up --build                          # Development (from repo root)
docker compose -f docker-compose.prod.yml up -d    # Production
```

## Architecture

**FastAPI microservice** with three main subsystems:

1. **Fetching** (`app/fetching/`) - Scrapes Greenhouse job boards, generates Gemini embeddings, upserts to MongoDB
2. **Applying** (`app/applying/greenhouse.py`) - Playwright-based form automation with AI-generated field values
3. **Database** (`app/db.py`) - Async MongoDB via Motor driver, collections: `jobs`, `users`

**AI Integration:**
- **Google Gemini** (`text-embedding-004`) - 768-dim embeddings for job descriptions
- **Google Gemini** (`gemini-2.5-flash-lite`) - Contextual form field answers via `app/ai.py`

**Key patterns:**
- Async/await throughout (FastAPI lifespan, Motor, Playwright async API)
- Rate limiting with sliding window (50 req/10s) in `app/rate_limiter.py`
- Upsert pattern using `greenhouse_id` as unique key

## Environment Variables

Required in `.env`:
```
MONGODB_URI=mongodb+srv://...
MONGODB_DB=app
GEMINI_API_KEY=AIza...
```

## Key Files

- `app/main.py` - FastAPI entry, lifespan manager, `/health` endpoint
- `app/applying/greenhouse.py` - Complex form filler (handles dropdowns, React-Select, file uploads)
- `app/fetching/scraper.py` - Job scraping orchestration with APScheduler
- `app/ai.py` - Gemini API calls for form field reasoning
- `manual_debug_greenhouse.py` - Visual debugging script with test data
