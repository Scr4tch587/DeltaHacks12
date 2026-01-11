# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**JobReels** - A hackathon project that delivers job listings as short-form vertical video content (TikTok/Reels style). Users swipe through AI-generated job summary videos, with semantic search matching jobs to user interests.

## Architecture

**Three Python microservices (FastAPI) + React Native mobile app:**

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Backend      │     │    Headless     │     │     Video       │
│   (port 8000)   │     │   (port 8001)   │     │   (port 8002)   │
│                 │     │                 │     │                 │
│ - Auth (JWT)    │     │ - Job scraping  │     │ - HLS video     │
│ - Semantic      │     │ - Playwright    │     │   streaming     │
│   search        │     │   automation    │     │ - DO Spaces CDN │
│ - User tracking │     │ - AI form fill  │     │                 │
└────────┬────────┘     └─────────────────┘     └────────┬────────┘
         │                                               │
         │              ┌─────────────────┐              │
         └──────────────┤  MongoDB Atlas  ├──────────────┘
                        │  (shared DB)    │
                        └─────────────────┘
                                                ┌─────────────────┐
┌─────────────────┐                             │ DigitalOcean    │
│    Frontend     │────────────────────────────▶│ Spaces CDN      │
│ (Expo/RN app)   │    HLS video streams        │ (video storage) │
└─────────────────┘                             └─────────────────┘
```

**Key data flows:**
- Backend generates Gemini embeddings for job search queries → MongoDB vector search
- Headless scrapes Greenhouse job boards, generates embeddings, stores jobs with `greenhouse_id` as unique key
- Video service returns CDN URLs for HLS playback (pre-generated videos stored in DO Spaces)
- Frontend uses expo-video with HLS streaming, swipe-to-browse pattern

## Commands

### Development (Docker)
```bash
# Start all services
docker compose up --build

# Production mode
docker compose -f docker-compose.prod.yml up -d --build
```

### Frontend (Expo)
```bash
cd frontend
npm install
npx expo start --tunnel     # For testing on physical devices
npx expo lint               # Lint check
```

### Headless Service
```bash
cd services/headless
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Visual debugging for job application flow
python manual_debug_greenhouse.py
```

### Text-to-Video Pipeline (standalone)
```bash
cd text_to_video
pip install -r requirements.txt
python main.py --topic "your topic" --step all    # Full pipeline
python main.py --topic "topic" --step video       # Reuse cached audio
python main.py --topic "topic" --force-regenerate # Bypass cache
```

## Key Patterns

**Authentication:** JWT tokens via `/auth/register` and `/auth/login`. Backend uses `get_current_user` dependency for protected routes. Tokens include user_id in `sub` claim.

**Semantic Search:** `POST /jobs/search` accepts text prompt + user_id, generates Gemini embedding, runs MongoDB vector search (`jobs_semantic_search` index), filters seen jobs, auto-marks returned jobs as seen.

**Job Tracking:** `user_job_views` collection tracks (user_id, greenhouse_id) pairs. Bulk check with `/user-job-views/bulk-check`.

**Video Playback:** Videos stored as HLS in DO Spaces (`/hls/{video_id}/master.m3u8`). Video service returns direct CDN URLs - no presigned URLs needed.

**Frontend Feed Control:** Set `EXPO_PUBLIC_DISABLE_FEED=true` to disable all video/network logic for auth-only testing.

## Environment Variables

Required in `.env`:
```
MONGODB_URI=mongodb+srv://...
MONGODB_DB=app
GEMINI_API_KEY=...
INTERNAL_API_KEY=...  # Shared secret for video uploads
```

Object storage (DigitalOcean Spaces for video, Vultr for backend):
```
DO_SPACES_CDN_URL=https://deltahacks-videos.tor1.cdn.digitaloceanspaces.com
VULTR_ENDPOINT=https://REGION.vultrobjects.com
VULTR_ACCESS_KEY=...
VULTR_SECRET_KEY=...
VULTR_BUCKET=...
```

## Service-Specific Documentation

- `services/headless/CLAUDE.md` - Job scraping, Playwright automation, AI form filling
- `text_to_video/CLAUDE.md` - Video generation pipeline (LLM script → TTS → FFmpeg)
