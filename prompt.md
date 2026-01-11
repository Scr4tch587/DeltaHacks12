# Cursor Prompt: Video Service generates HLS directly (Reels-feel MVP)

## Context
- Feed API returns video_ids (never repeat per user).
- Video service currently returns a video link given a video_id.
- Change: video service will now generate HLS directly using ffmpeg, with these fixed parameters:
  - Single rendition: 720x1280 portrait
  - H.264 + AAC
  - 2s segments
  - VOD playlist
  - Keyframes aligned to 2s boundaries (GOP = fps*2, scenecut off)
  - Segment files: `.ts`
- Frontend should receive a URL that points to an HLS manifest (`.m3u8`) which in turn references the segment URLs (“chunks”).

## Goal
Implement an endpoint that returns an HLS playback URL (manifest), and ensure generated HLS assets are addressable by the player.

### Required API contract
`GET /video/{video_id}` returns:

```json
{
  "video_id": "abc123",
  "playback": {
    "type": "hls",
    "url": "https://<BASE>/hls/abc123/master.m3u8"
  },
  "poster_url": "https://<BASE>/hls/abc123/poster.jpg",
  "duration_s": null,
  "aspect_ratio": "9:16"
}
```

Notes:

- `playback.url` MUST be a real `.m3u8` file URL.
    
- The `.m3u8` must reference segment URLs that are reachable from the client (absolute URLs or correct relative paths).
    
- It’s OK if poster/duration are null for hackathon.
    

## Implementation plan (Video service)

### 1) Storage / URL strategy (pick one; implement whichever matches the repo setup)

A) Generate and upload to Vultr Object Storage:

- Output folder:
    
    - `hls/{video_id}/master.m3u8`
        
    - `hls/{video_id}/720p/index.m3u8`
        
    - `hls/{video_id}/720p/seg_%03d.ts`
        
- Return playback URL based on env var `PUBLIC_HLS_BASE_URL`
    
    - e.g. `https://<bucket-or-cdn>/hls/{video_id}/master.m3u8`
        

OR

B) Serve HLS directly from the video service:

- Generate into local disk cache (e.g. `/var/cache/hls/{video_id}/...`)
    
- Mount a static route in FastAPI:
    
    - `/hls/{video_id}/master.m3u8`
        
    - `/hls/{video_id}/720p/index.m3u8`
        
    - `/hls/{video_id}/720p/seg_000.ts`
        
- IMPORTANT: If serving from FastAPI, ensure correct content-types and caching headers.
    

For hackathon simplicity, do NOT do per-segment signed URLs.

### 2) On-demand generation logic

- Add a function `ensure_hls(video_id) -> PlaybackUrls` that:
    
    - Checks if `master.m3u8` exists already (in object storage or local disk cache).
        
    - If exists, return URLs immediately.
        
    - If not, generate HLS using ffmpeg and then return URLs.
        
- Add a basic “in-progress” lock to avoid double-generation:
    
    - simplest: file lock or in-memory dict mutex keyed by video_id.
        

### 3) ffmpeg HLS generation (fixed spec)

Implement direct HLS encode:

- segment duration: 2 seconds
    
- VOD playlist
    
- H.264 + AAC
    
- scale to 720x1280 portrait (preserve aspect and pad/crop if needed)
    
- keyframes aligned to segment boundaries:
    
    - if fps assumed 30:
        
        - `-g 60 -keyint_min 60 -sc_threshold 0`
            

Implement as a single ffmpeg call producing:

- `720p/index.m3u8`
    
- `720p/seg_%03d.ts`
    

Then write a minimal `master.m3u8` referencing `720p/index.m3u8`.

### 4) Correct headers

If serving via FastAPI static:

- `.m3u8` Content-Type `application/vnd.apple.mpegurl`
    
- `.ts` Content-Type `video/mp2t`
    
- Add Cache-Control:
    
    - `.ts`: `public, max-age=31536000, immutable`
        
    - `.m3u8`: `public, max-age=60`
        

If uploading to Vultr, set these metadata headers on upload.

### 5) Update FastAPI endpoint

- Create Pydantic response models:
    
    - `Playback` { type: Literal["hls"], url: str }
        
    - `VideoResponse` { video_id, playback, poster_url, duration_s, aspect_ratio }
        
- Endpoint:
    
    - `GET /video/{video_id}`
        
    - Calls `ensure_hls(video_id)`
        
    - Returns response with `playback.url` pointing to `master.m3u8`
        

### 6) Frontend update (small)

- Update client to use `playback.url` directly in Expo AV Video source.
    
- Prefetch next 2 manifests:
    
    - `fetch(playback.url)` when a video enters “next” positions.
        
- Keep everything else the same.
    

## Deliverables

- Code implementing on-demand HLS generation in the video service
    
- Static hosting or Vultr upload wiring for HLS assets
    
- Updated `/video/{video_id}` response shape
    
- Minimal instructions in README:
    
    - env vars needed (PUBLIC_HLS_BASE_URL, paths, bucket credentials if applicable)
        
    - how to test a single video_id end-to-end
        

## Output

Make the changes directly in the repo, adapting to its structure and existing conventions.  
At the end, output a short test checklist:

- curl /video/{id} returns .m3u8 URL
    
- opening the .m3u8 in browser shows playlist text
    
- Expo app plays HLS smoothly and swipes without long buffering

FINAL NOTE: IF YOU LOOK AT VIDEO/APP/MAIN YOU CAN SEE THAT THE GET ENDPOINT WITH INPUT VIDEO_ID CURRENTLY RETURNS A COMPLETELY WRONG DATATYPE. IGNORE THAT. IT HAS NOT BEEN UPDATED YET. JUST WORK ON THE FUNCTIONALITY ASSUMING THAT THIS ENDPOINT WORKS AS DETAILED