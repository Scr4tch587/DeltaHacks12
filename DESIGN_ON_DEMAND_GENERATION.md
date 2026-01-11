# Design Plan: On-Demand Reel Generation with Caching Fallback

**Status:** PLAN ONLY — NO CODE  
**Target:** Hackathon-grade implementation (few hours)

---

## Summary

When a semantic search for jobs yields **insufficient videos above a similarity threshold**, the system will:
1. **Immediately return** the best available jobs that have videos (even if below threshold)
2. **In parallel**, trigger generation of new videos for high-matching jobs that lack videos
3. **Cache** newly generated videos (store in MongoDB + HLS assets in DigitalOcean Spaces)
4. **Avoid duplicates** via query fingerprinting and per-user concurrency limits

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Docker Network                                  │
│                                                                             │
│  ┌────────────────┐         ┌────────────────┐         ┌────────────────┐  │
│  │    Backend     │  HTTP   │    Video       │         │   Generator    │  │
│  │   (FastAPI)    │────────▶│   Service      │         │    Worker      │  │
│  │    :8000       │         │    :8002       │         │    (no port)   │  │
│  └───────┬────────┘         └────────────────┘         └───────┬────────┘  │
│          │                                                      │          │
│          │                                                      │          │
│          ▼                                                      ▼          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                         MongoDB Atlas                                │  │
│  │   • jobs (with embeddings)                                          │  │
│  │   • videos (video metadata, linked to jobs)                         │  │
│  │   • generation_jobs (job queue for worker)                          │  │
│  │   • user_job_views (seen tracking)                                  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│          │                                                      │          │
│          ▼                                                      ▼          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                    DigitalOcean Spaces (CDN)                        │  │
│  │   • hls/{video_id}/master.m3u8                                      │  │
│  │   • hls/{video_id}/poster.jpg                                       │  │
│  │   • hls/{video_id}/720p/*.ts                                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Service Ownership

| Responsibility | Owner |
|----------------|-------|
| Semantic search + fallback logic | **Backend** (FastAPI :8000) |
| Enqueue generation jobs | **Backend** |
| Video playback URLs | **Video Service** (FastAPI :8002) |
| Dequeue + execute video generation | **Generator Worker** (new service) |
| Upload HLS to DigitalOcean | **Generator Worker** |
| Index video in MongoDB | **Generator Worker** |

### Critical APIs

| Endpoint | Service | Purpose |
|----------|---------|---------|
| `POST /jobs/search` | Backend | Semantic search, returns jobs with videos, triggers generation |
| `GET /video/{video_id}` | Video Service | Returns HLS playback URL |
| (internal) MongoDB polling | Generator Worker | Poll `generation_jobs` collection |

---

## 2. Data Model Plan (MongoDB)

### 2.1 `jobs` Collection (existing, no changes needed)

```javascript
{
  _id: ObjectId,
  greenhouse_id: String,        // unique
  company_slug: String,
  title: String,
  description: String,          // used for embedding + video script
  embedding: [Number],          // 768 dims
  active: Boolean,
  // ... other fields
}
```

### 2.2 `videos` Collection (existing, add fields)

```javascript
{
  _id: ObjectId,
  video_id: String,             // UUID, unique — used in storage path
  greenhouse_id: String,        // FK to jobs.greenhouse_id (index this!)
  
  // Storage
  s3_key: String,               // "hls/{video_id}/master.m3u8"
  cdn_url: String,              // Full CDN URL for playback
  
  // Metadata
  template_id: String,          // Which template was used
  duration_seconds: Number,
  created_at: Date,
  
  // For vector search on videos (optional, for future)
  embedding: [Number],          // Copy from job, or generate from script
  
  // Status
  status: String                // "ready" | "failed"
}
```

**New indexes:**
```javascript
{ "greenhouse_id": 1 }          // Fast lookup: does job have video?
{ "video_id": 1 }               // unique
{ "status": 1, "created_at": -1 }
```

### 2.3 `generation_jobs` Collection (NEW)

```javascript
{
  _id: ObjectId,
  job_id: String,               // UUID for this generation job
  
  // What to generate
  greenhouse_id: String,        // Which job to make video for
  template_id: String,          // Random template selected at enqueue
  
  // Deduplication
  query_fingerprint: String,    // Hash of normalized query
  user_id: String,              // Who triggered this
  
  // State machine
  status: String,               // "queued" | "running" | "uploaded" | "indexed" | "ready" | "failed"
  
  // Tracking
  created_at: Date,
  updated_at: Date,
  started_at: Date,             // When worker picked it up
  completed_at: Date,
  
  // Results
  output_video_id: String,      // UUID of generated video (once complete)
  error: String,                // If failed
  retry_count: Number,          // For retry logic
  
  // Worker tracking
  worker_id: String             // Which worker instance picked this up
}
```

**Indexes:**
```javascript
{ "status": 1, "created_at": 1 }                    // Worker polling
{ "query_fingerprint": 1, "greenhouse_id": 1 }      // Dedup check
{ "user_id": 1, "status": 1 }                       // Per-user concurrency
{ "created_at": 1 }                                 // TTL: 24 hours
```

**TTL Index:**
```javascript
{ "created_at": 1 }, { expireAfterSeconds: 86400 }  // Auto-delete after 24h
```

### 2.4 `user_job_views` Collection (existing, no changes)

```javascript
{
  user_id: String,
  greenhouse_id: String,
  seen: Boolean
}
```

---

## 3. Query Fingerprinting Strategy (Dedup)

### Purpose
Prevent duplicate generation when:
- Same user searches same query multiple times
- Similar queries that would generate same video

### Fingerprint Computation

```python
import hashlib

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
    # Remove punctuation
    normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
    # Sort words for order-independence
    words = sorted(normalized.split())
    canonical = ' '.join(words)
    # Hash
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

### What goes into fingerprint
- **Included:** Raw query text (normalized)
- **NOT included:** user_id (same query = same videos for all users)
- **NOT included:** Timestamp, filters

### Dedup Check
Before enqueuing generation:
```python
existing = await generation_jobs.find_one({
    "query_fingerprint": fingerprint,
    "greenhouse_id": greenhouse_id,
    "status": {"$nin": ["failed"]}  # Allow retry if previously failed
})
if existing:
    # Skip — already queued or completed
    return
```

---

## 4. Fallback Logic Flow (Core Algorithm)

### Request: `POST /jobs/search`

```
Input: { text_prompt: str, user_id: str }
Output: { user_id, greenhouse_ids: [str], count: int, generation_triggered: bool }
```

### Step-by-Step Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Generate embedding for text_prompt (Gemini API)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Vector search: top K=20 jobs                                 │
│    Filter: active=true, greenhouse_id NOT IN user_seen          │
│    Returns: [{greenhouse_id, score}, ...]                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. For each result, check if job has video                      │
│    Query: videos.find({greenhouse_id: X, status: "ready"})      │
│    Split into:                                                  │
│      • jobs_with_videos: [{greenhouse_id, score, has_video}]    │
│      • jobs_without_videos: [{greenhouse_id, score}]            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Apply threshold T=0.75 to jobs_with_videos                   │
│    • above_threshold = jobs where score >= T                    │
│    • below_threshold = jobs where score < T                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Decision logic:                                              │
│                                                                 │
│    TARGET_COUNT = 5                                             │
│                                                                 │
│    IF len(above_threshold) >= TARGET_COUNT:                     │
│        return above_threshold[:TARGET_COUNT]                    │
│        (no generation needed)                                   │
│                                                                 │
│    ELSE:                                                        │
│        # Return best available (above + below threshold)        │
│        available = above_threshold + below_threshold            │
│        to_return = available[:TARGET_COUNT]                     │
│                                                                 │
│        # Calculate deficit                                      │
│        deficit = TARGET_COUNT - len(above_threshold)            │
│                                                                 │
│        # Trigger generation for jobs without videos             │
│        # that scored above threshold                            │
│        to_generate = [j for j in jobs_without_videos            │
│                       if j.score >= T][:deficit]                │
│                                                                 │
│        enqueue_generation(to_generate, query, user_id)          │
│        return to_return, generation_triggered=True              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Mark returned greenhouse_ids as seen for user                │
└─────────────────────────────────────────────────────────────────┘
```

### Parameters (Recommended Defaults)

| Parameter | Value | Description |
|-----------|-------|-------------|
| K (numCandidates) | 50 | Vector search candidate pool |
| K (limit) | 20 | Max jobs to evaluate |
| T (threshold) | 0.75 | Similarity score threshold (cosine, 0-1) |
| TARGET_COUNT | 5 | Desired number of results |
| MAX_GENERATE | 5 | Max videos to generate per request |
| MAX_USER_CONCURRENT | 2 | Max generation jobs per user |

### "Enough" Definition
- **Enough:** At least `TARGET_COUNT` jobs with videos above threshold T
- **Deficit:** `TARGET_COUNT - len(above_threshold)`

### Concurrency Limits

Before enqueuing generation for a user:
```python
active_jobs = await generation_jobs.count_documents({
    "user_id": user_id,
    "status": {"$in": ["queued", "running"]}
})

if active_jobs >= MAX_USER_CONCURRENT:
    # Don't enqueue more, user already has jobs in flight
    return
```

---

## 5. Job Lifecycle + Orchestration

### State Machine

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
    ┌─────────┐  worker   ┌─────────┐  upload   ┌──────────┐  index   ┌─────────┐
    │ queued  │──picks───▶│ running │──done────▶│ uploaded │──done───▶│  ready  │
    └─────────┘   up      └────┬────┘           └──────────┘          └─────────┘
                               │
                               │ error
                               ▼
                          ┌─────────┐
                          │ failed  │
                          └─────────┘
```

### State Transitions

| From | To | Trigger | Who Updates |
|------|-----|---------|-------------|
| (none) | `queued` | Backend enqueues job | Backend |
| `queued` | `running` | Worker claims job | Worker |
| `running` | `uploaded` | HLS uploaded to DO Spaces | Worker |
| `uploaded` | `indexed` | Video doc inserted in MongoDB | Worker |
| `indexed` | `ready` | Generation complete | Worker |
| `running` | `failed` | Any error | Worker |
| `failed` | `queued` | Retry (if retry_count < 3) | Worker |

### Worker Claim (Idempotency)

Use atomic `findOneAndUpdate` to claim jobs:

```python
job = await generation_jobs.find_one_and_update(
    {
        "status": "queued",
        "created_at": {"$lt": datetime.utcnow() - timedelta(seconds=5)}  # 5s delay
    },
    {
        "$set": {
            "status": "running",
            "started_at": datetime.utcnow(),
            "worker_id": WORKER_ID
        }
    },
    sort=[("created_at", 1)],  # FIFO
    return_document=ReturnDocument.AFTER
)
```

### Crash Recovery

If worker crashes mid-run:
- Jobs stuck in `running` for > 10 minutes are considered stale
- Background task resets stale jobs to `queued` (if retry_count < 3)

```python
# Run every 5 minutes
await generation_jobs.update_many(
    {
        "status": "running",
        "started_at": {"$lt": datetime.utcnow() - timedelta(minutes=10)}
    },
    {
        "$set": {"status": "queued"},
        "$inc": {"retry_count": 1}
    }
)
```

### Retry Logic

| Error Type | Retryable | Action |
|------------|-----------|--------|
| FFmpeg crash | Yes | Retry up to 3 times |
| TTS API error | Yes | Retry with backoff |
| Script generation fail | Yes | Retry up to 3 times |
| Upload to DO fails | Yes | Retry up to 3 times |
| MongoDB insert fails | Yes | Retry (upload already done) |
| Invalid job description | No | Mark failed, don't retry |

```python
MAX_RETRIES = 3

if job["retry_count"] >= MAX_RETRIES:
    await generation_jobs.update_one(
        {"_id": job["_id"]},
        {"$set": {"status": "failed", "error": "Max retries exceeded"}}
    )
```

---

## 6. Storage Layout (DigitalOcean Spaces)

### Directory Structure

```
deltahacksvideos/                    # Bucket
├── hls/
│   ├── {video_id}/                   # UUID, e.g., "a1b2c3d4-e5f6-..."
│   │   ├── master.m3u8               # HLS manifest
│   │   ├── poster.jpg                # Thumbnail
│   │   └── 720p/
│   │       ├── playlist.m3u8
│   │       └── segment_000.ts
│   │       └── segment_001.ts
│   │       └── ...
│   ├── {video_id}/
│   │   └── ...
```

### Key Generation

```python
import uuid

video_id = str(uuid.uuid4())
s3_key_manifest = f"hls/{video_id}/master.m3u8"
s3_key_poster = f"hls/{video_id}/poster.jpg"
```

### CDN URLs

```python
CDN_BASE = "https://deltahacksvideos.tor1.cdn.digitaloceanspaces.com"
playback_url = f"{CDN_BASE}/hls/{video_id}/master.m3u8"
poster_url = f"{CDN_BASE}/hls/{video_id}/poster.jpg"
```

### Caching Headers

Set on upload:
```python
s3_client.put_object(
    Bucket=bucket,
    Key=s3_key,
    Body=content,
    ContentType="application/vnd.apple.mpegurl",  # for .m3u8
    ACL="public-read",
    CacheControl="public, max-age=31536000"  # 1 year (immutable content)
)
```

### video_id Assignment

- Generated at **enqueue time** (in Backend)
- Stored in `generation_jobs.output_video_id`
- Used by Worker when uploading
- Ensures deterministic storage paths

---

## 7. Frontend Behavior Plan (Minimal)

### Client Learning About New Videos

**Strategy:** Client re-calls `/jobs/search` with same query

```
1. User searches "python developer"
2. Backend returns 3 jobs with videos (below TARGET_COUNT)
   Response: { greenhouse_ids: [...], generation_triggered: true }
3. Client shows the 3 videos
4. After user watches them (or after N seconds), client re-searches
5. Backend returns 5 jobs now (new videos generated)
6. Client shows new videos
```

### Response Schema Change

```python
class SearchJobsResponse(BaseModel):
    user_id: str
    greenhouse_ids: List[str]      # Only jobs WITH videos
    count: int
    generation_triggered: bool     # True if new videos are being generated
    generation_job_ids: List[str]  # Optional: for debugging
```

### Polling Logic (Client-Side)

```typescript
// Pseudocode
const POLL_INTERVAL_MS = 10000;  // 10 seconds

async function searchWithRetry(query: string) {
  const result = await api.searchJobs(query);
  
  if (result.generation_triggered && result.count < TARGET_COUNT) {
    // New videos being generated, poll again later
    setTimeout(() => {
      searchWithRetry(query);  // Will get new videos
    }, POLL_INTERVAL_MS);
  }
  
  return result;
}
```

### UX Considerations

- **Never block:** Always return something playable immediately
- **No loading state:** Don't show "generating..." — just show available videos
- **Silent refresh:** When new videos are ready, they appear on next search
- **Graceful:** If generation fails, user just sees fewer videos (acceptable)

---

## 8. Observability + Debugging (Hackathon Friendly)

### What to Log

| Step | Log Level | What to Log |
|------|-----------|-------------|
| Search request | INFO | `user_id, query_fingerprint, query_length` |
| Vector search results | DEBUG | `num_results, scores, has_video_counts` |
| Threshold decision | INFO | `above_threshold_count, below_threshold_count, deficit` |
| Generation enqueued | INFO | `job_id, greenhouse_id, template_id, user_id` |
| Worker claims job | INFO | `job_id, worker_id` |
| Video generation starts | INFO | `job_id, greenhouse_id` |
| TTS complete | DEBUG | `job_id, audio_file_count, duration_ms` |
| FFmpeg complete | DEBUG | `job_id, video_duration_s` |
| Upload complete | INFO | `job_id, video_id, s3_key, size_bytes` |
| DB index complete | INFO | `job_id, video_id` |
| Generation failed | ERROR | `job_id, error, retry_count` |

### Admin/Debug Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/admin/generation-jobs` | GET | List all generation jobs (paginated) |
| `/admin/generation-jobs/{job_id}` | GET | Get specific job status |
| `/admin/generation-jobs/{job_id}/retry` | POST | Force retry a failed job |
| `/admin/generation-jobs/stats` | GET | Counts by status |
| `/admin/videos/orphaned` | GET | Videos with no job reference |
| `/health` | GET | Include `generator_queue_depth` |

### Stats Endpoint Response

```json
{
  "generation_jobs": {
    "queued": 3,
    "running": 1,
    "ready": 150,
    "failed": 2
  },
  "videos": {
    "total": 153,
    "ready": 150
  },
  "jobs_with_videos": 150,
  "jobs_without_videos": 50
}
```

---

## 9. Failure Modes + Safe Fallbacks

### Failure: Vector Search Returns No Results

**Cause:** Query too specific, no matching jobs  
**Detection:** Empty results from `$vectorSearch`  
**Fallback:** Return empty array, `generation_triggered: false`  
**User sees:** Empty feed (acceptable edge case)

### Failure: Vector Search Returns Low Scores (Junk)

**Cause:** Query doesn't match any job descriptions well  
**Detection:** All scores < 0.5 (very low)  
**Fallback:** Still return best available with videos (even if poor match)  
**User sees:** Somewhat relevant videos (better than nothing)

### Failure: Generator Worker Is Down/Slow

**Cause:** Worker crashed or backlogged  
**Detection:** Jobs stuck in `queued` for > 5 minutes  
**Fallback:** 
- User gets whatever videos already exist
- Generation happens eventually when worker recovers
- No user-facing error  
**User sees:** Fewer videos than ideal, but feed still works

### Failure: Upload to DigitalOcean Fails

**Cause:** Network issue, auth failure, bucket issue  
**Detection:** S3 `put_object` throws exception  
**Fallback:** 
- Mark job as failed, retry up to 3 times
- Exponential backoff (1s, 2s, 4s)  
**User sees:** Video just doesn't appear (silent failure)

### Failure: MongoDB Index Insert Fails (After Upload)

**Cause:** DB connection issue, duplicate key  
**Detection:** `insert_one` throws exception  
**Fallback:**
- Video is in S3 but not indexed
- Job stuck in `uploaded` status
- Recovery: Worker retries just the index step  
**User sees:** Video exists but not discoverable (rare, recoverable)

### Failure: Duplicate Generation Jobs

**Cause:** User rapidly searches same query  
**Detection:** `query_fingerprint + greenhouse_id` already exists  
**Fallback:** Skip enqueue, job already in progress  
**User sees:** Normal behavior (dedup working)

### Failure: User Spams Different Queries

**Cause:** Malicious or bored user  
**Detection:** More than 2 concurrent jobs for user  
**Fallback:** Don't enqueue new jobs, return what's available  
**User sees:** Available videos, no generation triggered

### Failure: Job Description Is Too Short/Invalid

**Cause:** Job in DB has empty or tiny description  
**Detection:** Script generator fails with validation error  
**Fallback:** Mark as failed (non-retryable), skip this job  
**User sees:** This job never gets a video (acceptable)

### Golden Rule

> **Never break scrolling. Always return something.**

Even if everything is on fire:
- Return hardcoded fallback video IDs
- Return random jobs with videos
- Return empty array (frontend shows "no results")

---

## 10. Sequence Diagram

```
User                    Frontend              Backend                Generator Worker         MongoDB              DO Spaces
  │                        │                     │                        │                     │                     │
  │ search "python dev"    │                     │                        │                     │                     │
  │───────────────────────▶│                     │                        │                     │                     │
  │                        │ POST /jobs/search   │                        │                     │                     │
  │                        │────────────────────▶│                        │                     │                     │
  │                        │                     │ generate embedding     │                     │                     │
  │                        │                     │────────────────────────────────────────────▶│                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │ vector search jobs     │                     │                     │
  │                        │                     │────────────────────────────────────────────▶│                     │
  │                        │                     │◀────────────────────────────────────────────│                     │
  │                        │                     │ [job1:0.9, job2:0.85, job3:0.7, ...]        │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │ check which have videos│                     │                     │
  │                        │                     │────────────────────────────────────────────▶│                     │
  │                        │                     │◀────────────────────────────────────────────│                     │
  │                        │                     │ [job1:yes, job2:no, job3:yes]               │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │ above threshold: job1, job3 (only 2!)      │                     │
  │                        │                     │ deficit = 5 - 2 = 3                        │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │ enqueue generation for job2                │                     │
  │                        │                     │────────────────────────────────────────────▶│                     │
  │                        │                     │                        │                     │                     │
  │                        │ {greenhouse_ids: [job1,job3], generation_triggered: true}        │                     │
  │                        │◀────────────────────│                        │                     │                     │
  │ show 2 videos          │                     │                        │                     │                     │
  │◀───────────────────────│                     │                        │                     │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │                        │ poll for jobs       │                     │
  │                        │                     │                        │────────────────────▶│                     │
  │                        │                     │                        │◀────────────────────│                     │
  │                        │                     │                        │ claim job for job2  │                     │
  │                        │                     │                        │────────────────────▶│                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │                        │ generate script     │                     │
  │                        │                     │                        │ generate TTS        │                     │
  │                        │                     │                        │ render video        │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │                        │ upload HLS          │                     │
  │                        │                     │                        │────────────────────────────────────────▶│
  │                        │                     │                        │◀────────────────────────────────────────│
  │                        │                     │                        │                     │                     │
  │                        │                     │                        │ insert video doc    │                     │
  │                        │                     │                        │────────────────────▶│                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │                        │ mark job "ready"    │                     │
  │                        │                     │                        │────────────────────▶│                     │
  │                        │                     │                        │                     │                     │
  │ (10s later)            │                     │                        │                     │                     │
  │ swipe / re-search      │                     │                        │                     │                     │
  │───────────────────────▶│                     │                        │                     │                     │
  │                        │ POST /jobs/search   │                        │                     │                     │
  │                        │────────────────────▶│                        │                     │                     │
  │                        │                     │                        │                     │                     │
  │                        │                     │ (same flow, now job2 has video)             │                     │
  │                        │                     │                        │                     │                     │
  │                        │ {greenhouse_ids: [job1,job2,job3,...], generation_triggered: false}                     │
  │                        │◀────────────────────│                        │                     │                     │
  │ show 5 videos!         │                     │                        │                     │                     │
  │◀───────────────────────│                     │                        │                     │                     │
```

---

## 11. Recommended Parameter Defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| `VECTOR_SEARCH_LIMIT` | 20 | Max jobs to evaluate per search |
| `VECTOR_SEARCH_CANDIDATES` | 50 | numCandidates for vector search |
| `SIMILARITY_THRESHOLD` | 0.75 | Score threshold (cosine, 0-1) |
| `TARGET_COUNT` | 5 | Desired number of results |
| `MAX_GENERATE_PER_REQUEST` | 5 | Max videos to enqueue per search |
| `MAX_USER_CONCURRENT_JOBS` | 2 | Max generation jobs per user |
| `WORKER_POLL_INTERVAL_S` | 5 | How often worker checks for jobs |
| `JOB_TIMEOUT_MINUTES` | 10 | After this, assume worker crashed |
| `MAX_RETRIES` | 3 | Max retry attempts per job |
| `JOB_TTL_HOURS` | 24 | Auto-delete old generation jobs |
| `CLIENT_POLL_INTERVAL_S` | 10 | Suggested re-search interval |

---

## 12. Implementation Checklist

### Phase 1: Data Model
- [ ] Add `greenhouse_id` index to `videos` collection
- [ ] Create `generation_jobs` collection with indexes
- [ ] Add TTL index on `generation_jobs.created_at`

### Phase 2: Backend Changes
- [ ] Add `compute_query_fingerprint()` utility
- [ ] Modify `/jobs/search` to check video existence
- [ ] Add threshold logic and deficit calculation
- [ ] Add generation job enqueueing
- [ ] Add per-user concurrency check
- [ ] Update response schema

### Phase 3: Generator Worker
- [ ] Create new Docker service (`services/generator/`)
- [ ] Implement job claiming (atomic findOneAndUpdate)
- [ ] Integrate `text_to_video` pipeline
- [ ] Implement DO Spaces upload
- [ ] Implement video document creation
- [ ] Add crash recovery (stale job reset)
- [ ] Add health check

### Phase 4: Admin Endpoints
- [ ] `GET /admin/generation-jobs`
- [ ] `GET /admin/generation-jobs/{job_id}`
- [ ] `GET /admin/generation-jobs/stats`

### Phase 5: Testing
- [ ] Test with 0 videos (all generation)
- [ ] Test with some videos (partial generation)
- [ ] Test with all videos (no generation)
- [ ] Test concurrent user limits
- [ ] Test worker crash recovery
- [ ] Test deduplication

---

## 13. Docker Compose Addition

```yaml
# Add to existing docker-compose.yml

generator:
  build: ./services/generator
  environment:
    - MONGODB_URI=${MONGODB_URI}
    - DO_SPACES_ENDPOINT=${DO_SPACES_ENDPOINT}
    - DO_SPACES_ACCESS_KEY=${DO_SPACES_ACCESS_KEY}
    - DO_SPACES_SECRET_KEY=${DO_SPACES_SECRET_KEY}
    - DO_SPACES_BUCKET=${DO_SPACES_BUCKET}
    - DO_SPACES_CDN_URL=${DO_SPACES_CDN_URL}
    - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    - FISH_AUDIO_API_KEY=${FISH_AUDIO_API_KEY}
    - WORKER_ID=generator-1
  volumes:
    - ./text_to_video:/app/text_to_video:ro
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "python", "-c", "print('ok')"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

**END OF PLAN**
