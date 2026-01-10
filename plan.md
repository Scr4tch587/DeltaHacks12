# Technical Architecture Overview

## High-Level Goal
Design a hackathon-scale system that:
- Is deployable on a single cloud VM (Vultr)
- Uses MongoDB Atlas as the core data + intelligence layer
- Automates job applications on **Greenhouse** job boards
- Uses Gemini API for embeddings (`text-embedding-005`) and generation (`gemini-3.0-flash`)

## Core Flow
1. Hard-coded list of companies using Greenhouse (with icons)
2. Scrape all job postings from each company's Greenhouse board
3. Embed job descriptions for semantic search
4. User selects job → system auto-fills Greenhouse application
5. Return unfilled fields to user with available options (dropdowns, etc.)
6. User completes remaining fields → submit application

---

## Infrastructure Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Compute | Vultr VM (Ubuntu) + Docker Compose | Host all services |
| Database | MongoDB Atlas | Data, vectors, TTL caching |
| Object Storage | Vultr Object Storage (S3-compatible) | Video files |
| AI Provider | Gemini API | Embeddings (`text-embedding-005`) + Generation (`gemini-3.0-flash`) |
| Networking | Tailscale (optional) | Private service mesh |

---

## Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Network                          │
│                                                             │
│  ┌────────────┐    HTTP     ┌──────────────┐               │
│  │  Backend   │────────────▶│   Headless   │               │
│  │  (FastAPI) │             │  (Playwright) │               │
│  │  :8000     │             │  :8001        │               │
│  └─────┬──────┘             └──────────────┘               │
│        │                                                    │
│        │ HTTP                                               │
│        ▼                                                    │
│  ┌──────────────┐                                          │
│  │    Video     │                                          │
│  │   (FFmpeg)   │                                          │
│  │   :8002      │                                          │
│  └──────────────┘                                          │
└─────────────────────────────────────────────────────────────┘
         │
         │ HTTPS
         ▼
   MongoDB Atlas
```

### Communication Pattern

| Route | Timeout | Retries |
|-------|---------|---------|
| Backend → Headless | 60s | 2 |
| Backend → Video | 300s | 1 |
| Backend → MongoDB | 10s | 3 |
| Backend → Gemini | 30s | 2 |

All retries use exponential backoff (1s, 2s, 4s).

---

## Services

### 1. Backend API (FastAPI) - Port 8000 (public)
- Orchestrates all operations
- Handles vector search via Atlas
- Generates embeddings via Gemini API
- Issues video playback URLs

### 2. Headless Service (Playwright) - Port 8001 (internal)
Optimized specifically for Greenhouse job boards.

```yaml
POST /greenhouse/scrape-jobs
  Headers: X-Internal-Key: {secret}
  Request: { company_slug }  # e.g., "stripe", "figma"
  Response: {
    success: true,
    company_slug,
    jobs: [{ greenhouse_id, title, location, department, url }],
    scraped_at
  }

POST /greenhouse/scrape-job-detail
  Headers: X-Internal-Key: {secret}
  Request: { job_url }
  Response: {
    success: true,
    greenhouse_id,
    title,
    description,      # Full job description text for embedding
    requirements,
    location,
    department
  }

POST /greenhouse/apply
  Headers: X-Internal-Key: {secret}
  Request: {
    job_url,
    user_data: { name, email, phone, resume_url, linkedin_url, ... }
  }
  Response: {
    success: true,
    filled_fields: ["name", "email", "phone", "resume"],
    unfilled_fields: [
      {
        field_id: "question_123",
        label: "How did you hear about us?",
        type: "select",           # "text" | "select" | "radio" | "checkbox" | "textarea"
        required: true,
        options: ["LinkedIn", "Referral", "Job Board", "Other"]  # Only for select/radio
      },
      {
        field_id: "question_456",
        label: "Years of experience with Python",
        type: "text",
        required: true,
        options: null
      }
    ],
    application_state_id    # ID to resume this application later
  }

POST /greenhouse/submit
  Headers: X-Internal-Key: {secret}
  Request: {
    application_state_id,
    field_answers: { "question_123": "LinkedIn", "question_456": "5" }
  }
  Response: { success: true, confirmation_id } | { success: false, error }

GET /health
  Response: { status, browser_ready }
```

### 3. Video Service (FFmpeg) - Port 8002 (internal)
Uses **Gemini 3.0 Flash** (`gemini-3.0-flash`) to generate video scripts from job data.

```yaml
POST /generate
  Headers: X-Internal-Key: {secret}
  Request: { job_id, template_id, params, output_format }
  Response: { job_id, status: "queued", estimated_duration_seconds }

  # Internally:
  # 1. Fetch job data from MongoDB
  # 2. Generate script via Gemini 3.0 Flash
  # 3. Render video with FFmpeg
  # 4. Upload to Vultr Object Storage

GET /jobs/{job_id}/status
  Response: { job_id, status, progress_percent, result?, error? }

GET /health
  Response: { status, ffmpeg_version, queue_depth }
```

---

## Public API Endpoints

**Auth:** All endpoints (except `/health`) require `X-API-Key` header.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (no auth) |
| GET | `/companies` | List all supported companies |
| GET | `/companies/{slug}/jobs` | List jobs for a company |
| POST | `/companies/{slug}/sync` | Trigger job sync for company |
| GET | `/jobs` | List all jobs (paginated) |
| GET | `/jobs/{job_id}` | Get specific job |
| POST | `/search/semantic` | Vector similarity search |
| POST | `/applications/start` | Start application, get unfilled fields |
| POST | `/applications/{id}/complete` | Submit user's answers to unfilled fields |
| GET | `/applications` | List user's applications |
| GET | `/applications/{id}` | Get application status |
| GET | `/videos` | List videos |
| POST | `/videos/generate` | Trigger video generation |
| GET | `/videos/{video_id}` | Get video + playback URL |

### Key Request/Response Shapes

```python
# GET /companies
Response: {
  "companies": [
    { "slug": "stripe", "name": "Stripe", "icon_url": "...", "job_count": 142 },
    { "slug": "figma", "name": "Figma", "icon_url": "...", "job_count": 87 }
  ]
}

# POST /companies/{slug}/sync
Response: { "status": "syncing", "jobs_found": 142 }

# POST /search/semantic
Request:  { "query": str, "company_slugs?": [str], "limit?": int }
Response: { "results": [{ "id", "score", "title", "company", "location" }] }

# POST /applications/start
Request:  { "job_id": str, "user_data": { name, email, phone, resume_url, linkedin_url, ... } }
Response: {
  "application_id": str,
  "status": "pending_user_input",
  "filled_fields": ["name", "email", "phone", "resume"],
  "unfilled_fields": [
    {
      "field_id": "question_123",
      "label": "How did you hear about us?",
      "type": "select",
      "required": true,
      "options": ["LinkedIn", "Referral", "Job Board", "Other"]
    }
  ]
}

# POST /applications/{id}/complete
Request:  { "field_answers": { "question_123": "LinkedIn", "question_456": "5" } }
Response: { "status": "submitted", "confirmation_id": str } | { "status": "failed", "error": str }
```

### Pagination
```
GET /videos?limit=20&cursor=<base64>
Response: { "data": [...], "pagination": { "next_cursor", "has_more" } }
```

### Error Format
```json
{ "error": "error_code", "message": "Human-readable", "details?": {} }
```

| Status | Code | When |
|--------|------|------|
| 400 | `bad_request` | Invalid body |
| 401 | `unauthorized` | Bad/missing API key |
| 404 | `not_found` | Resource missing |
| 422 | `validation_error` | Validation failed |
| 429 | `rate_limited` | Too many requests |
| 503 | `service_unavailable` | Dependency down |

---

## Data Schemas

### companies (hard-coded seed data)
```javascript
{
  _id: ObjectId,
  slug: String,                 // "stripe", "figma" - unique
  name: String,                 // "Stripe", "Figma"
  icon_url: String,             // Company logo
  greenhouse_url: String,       // "https://boards.greenhouse.io/stripe"
  job_count: Number,            // Cached count
  last_synced_at: Date
}
```

### jobs
```javascript
{
  _id: ObjectId,
  greenhouse_id: String,        // Greenhouse's internal ID - unique
  company_slug: String,         // Reference to company
  url: String,                  // Full Greenhouse job URL
  title: String,
  department: String?,
  location: String,
  description: String,          // Full job description for embedding
  requirements: [String]?,
  scraped_at: Date,
  embedding: [Number],          // 768 dims (text-embedding-005)
  embedding_model: String,
  status: String                // "pending" | "ready" | "embedding_failed"
}
```

### applications
```javascript
{
  _id: ObjectId,
  job_id: ObjectId,
  user_id: String?,
  status: String,               // "pending_user_input" | "submitting" | "submitted" | "failed"

  // What we auto-filled
  filled_fields: [String],      // ["name", "email", "phone", "resume"]

  // What user needs to complete
  unfilled_fields: [{
    field_id: String,
    label: String,
    type: String,               // "text" | "select" | "radio" | "checkbox" | "textarea"
    required: Boolean,
    options: [String]?          // For select/radio/checkbox
  }],

  // User's answers (populated after /complete)
  field_answers: Object?,       // { "question_123": "LinkedIn" }

  // Browser state for resuming application
  application_state_id: String, // Internal reference to Playwright state

  confirmation_id: String?,     // From Greenhouse after successful submit
  error: String?,               // If failed

  created_at: Date,
  updated_at: Date,
  expires_at: Date              // TTL - application states expire after 1 hour
}
```

### videos
```javascript
{
  _id: ObjectId,
  title: String,
  description: String?,
  template_id: String,
  object_key: String,           // S3 key
  thumbnail_key: String?,
  duration_seconds: Number,
  file_size_bytes: Number,
  job_id: ObjectId,
  tags: [String],
  embedding: [Number],
  embedding_model: String,
  engagement: { views, completions, shares, avg_watch_percent },
  status: String,               // "processing" | "ready" | "failed"
  created_at: Date,
  updated_at: Date
}
```

### events
```javascript
{
  _id: ObjectId,
  type: String,                 // "view" | "apply_start" | "apply_complete" | "search"
  resource_type: String,        // "job" | "video" | "application"
  resource_id: ObjectId,
  context: { session_id, referrer, device_type },
  timestamp: Date,              // TTL anchor
  data: Object
}
```

---

## Indexes

```javascript
// companies
{ "slug": 1 }                         // unique

// jobs
{ "greenhouse_id": 1 }                // unique
{ "company_slug": 1 }
{ "status": 1 }

// applications
{ "job_id": 1 }
{ "user_id": 1, "status": 1 }
{ "expires_at": 1 }                   // TTL: 0 (uses field value)

// videos
{ "tags": 1 }                         // multikey
{ "job_id": 1 }
{ "status": 1, "created_at": -1 }

// events
{ "timestamp": 1 }                    // TTL: 90 days (7776000s)
{ "resource_type": 1, "resource_id": 1 }
```

---

## Vector Search

**Model:** `text-embedding-005`
**Dimensions:** 768 (configurable via `output_dimensionality`, supports 128-3072)
**Similarity:** cosine
**Task Types:** `RETRIEVAL_DOCUMENT` for indexing jobs, `RETRIEVAL_QUERY` for search queries

### Atlas Vector Search Index (jobs collection)
```json
{
  "name": "jobs_semantic_search",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine" },
      { "type": "filter", "path": "status" },
      { "type": "filter", "path": "company_slug" }
    ]
  }
}
```

### Query Pattern
```javascript
[
  {
    "$vectorSearch": {
      "index": "jobs_semantic_search",
      "path": "embedding",
      "queryVector": [...],
      "numCandidates": limit * 10,
      "limit": limit,
      "filter": { "status": "ready", "company_slug": { "$in": [...] } }
    }
  },
  { "$addFields": { "score": { "$meta": "vectorSearchScore" } } },
  { "$project": { "embedding": 0 } }
]
```

### Job Sync & Embedding Flow
1. `POST /companies/{slug}/sync` triggers scrape of Greenhouse board
2. For each job: save with `status: "pending"`
3. Scrape full job description via `/greenhouse/scrape-job-detail`
4. Generate embedding via Gemini `embedContent` API with `task_type: RETRIEVAL_DOCUMENT`
5. Update job with embedding, set `status: "ready"`
6. On failure: set `status: "embedding_failed"`

### Embedding API Call
```python
# Index job descriptions
result = client.models.embed_content(
    model="text-embedding-005",
    contents=job_description,
    config=types.EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=768
    )
)

# Search queries
result = client.models.embed_content(
    model="text-embedding-005",
    contents=user_query,
    config=types.EmbedContentConfig(
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=768
    )
)
```

---

## Docker Compose

```yaml
version: "3.8"

services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - VULTR_ENDPOINT=${VULTR_ENDPOINT}
      - VULTR_ACCESS_KEY=${VULTR_ACCESS_KEY}
      - VULTR_SECRET_KEY=${VULTR_SECRET_KEY}
      - VULTR_BUCKET=${VULTR_BUCKET}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - HEADLESS_URL=http://headless:8001
      - VIDEO_URL=http://video:8002
      - INTERNAL_SERVICE_KEY=${INTERNAL_SERVICE_KEY}
      - API_KEY=${API_KEY}
    depends_on:
      headless: { condition: service_healthy }
      video: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  headless:
    build: ./headless
    environment:
      - INTERNAL_SERVICE_KEY=${INTERNAL_SERVICE_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      start_period: 30s

  video:
    build: ./video
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - VULTR_ENDPOINT=${VULTR_ENDPOINT}
      - VULTR_ACCESS_KEY=${VULTR_ACCESS_KEY}
      - VULTR_SECRET_KEY=${VULTR_SECRET_KEY}
      - VULTR_BUCKET=${VULTR_BUCKET}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - INTERNAL_SERVICE_KEY=${INTERNAL_SERVICE_KEY}
    volumes:
      - ./video/templates:/app/templates:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
```

### Dockerfiles

**Backend:** `python:3.11-slim` + uvicorn on :8000
**Headless:** `mcr.microsoft.com/playwright/python:v1.40.0-jammy` + uvicorn on :8001
**Video:** `python:3.11-slim` + `apt install ffmpeg` + uvicorn on :8002

---

## Environment Variables

```bash
# MongoDB Atlas
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/dbname

# Vultr Object Storage
VULTR_ENDPOINT=https://ewr1.vultrobjects.com
VULTR_ACCESS_KEY=
VULTR_SECRET_KEY=
VULTR_BUCKET=

# Gemini API
GEMINI_API_KEY=your-gemini-api-key

# Service Auth
INTERNAL_SERVICE_KEY=   # Shared secret for internal services
API_KEY=                # Client API key

# Optional
ENV=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000
```

---

## Error Handling

| Scenario | Response | Behavior |
|----------|----------|----------|
| Invalid request | 400 | Return validation errors |
| Bad API key | 401 | Reject |
| Resource missing | 404 | Return error |
| Internal service down | 503 | Retry with backoff, then fail |
| Gemini API error | 502 | Retry with backoff |
| MongoDB down | 503 | Fail (cannot operate) |

**Retry pattern:** exponential backoff (1s, 2s, 4s), max 3 attempts
**Circuit breaker:** Open after 5 consecutive failures, recover after 30s

**Graceful degradation:**
- Headless down → Return cached data if available
- Video down → Queue request, return "processing"
- Gemini down → Skip embedding, mark for retry

---

## Security

- **Public API:** `X-API-Key` header required
- **Internal services:** `X-Internal-Key` header + network isolation
- **MongoDB:** Atlas-managed TLS + IP allowlist
- **Object storage:** Public-read URLs for video playback
- **Secrets:** Environment variables only, never committed

---

## Job State Machine

```
(none) → pending → processing → completed
                 ↘            ↗
                   → failed
                   → timeout
```

Status stored in MongoDB, polled by client via `GET /jobs/{id}` or `GET /videos/{id}`.

---

## Seed Data: Supported Companies

```javascript
// Hard-coded in database initialization
[
  { slug: "stripe", name: "Stripe", greenhouse_url: "https://boards.greenhouse.io/stripe", icon_url: "..." },
  { slug: "figma", name: "Figma", greenhouse_url: "https://boards.greenhouse.io/figma", icon_url: "..." },
  { slug: "notion", name: "Notion", greenhouse_url: "https://boards.greenhouse.io/notion", icon_url: "..." },
  { slug: "airbnb", name: "Airbnb", greenhouse_url: "https://boards.greenhouse.io/airbnb", icon_url: "..." },
  // Add more companies as needed
]
```

---

## Application Flow Diagram

```
User selects job
        │
        ▼
POST /applications/start
        │
        ▼
Headless: Navigate to Greenhouse, auto-fill known fields
        │
        ▼
Return: filled_fields + unfilled_fields (with options)
        │
        ▼
User answers unfilled questions in UI
        │
        ▼
POST /applications/{id}/complete
        │
        ▼
Headless: Fill remaining fields, submit
        │
        ▼
Return: confirmation_id or error
```

---

## Implementation Checklist

- [ ] Docker Compose starts all 3 services
- [ ] `GET /health` returns healthy
- [ ] `GET /companies` returns seeded company list with icons
- [ ] `POST /companies/{slug}/sync` scrapes Greenhouse job listings
- [ ] Jobs have embeddings generated after sync
- [ ] `POST /search/semantic` returns jobs ranked by relevance
- [ ] `POST /applications/start` auto-fills Greenhouse form, returns unfilled fields
- [ ] Unfilled fields include options for dropdowns/radios
- [ ] `POST /applications/{id}/complete` submits with user's answers
- [ ] Application state expires after 1 hour (TTL)
- [ ] 401 returned without valid API key
- [ ] Internal services reject requests without internal key
