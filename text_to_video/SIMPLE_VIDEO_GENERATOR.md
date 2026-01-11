# Simple Video Generator - Summary

## What Was Created

### 1. Main Function: `generate_video_from_text()`
**File:** `text_to_video/main.py`

A simple function that takes:
- `job_description` (text string) - NO file reading needed
- `output_path` (directory path) - Where to save all files
- `output_name` (optional) - Video filename

```python
generate_video_from_text(
    job_description="Senior Python Developer...",
    output_path="/tmp/videos",
)
```

### 2. Test Script: `test_simple.py`
**File:** `text_to_video/test_simple.py`

Shows how to use the function:
```bash
cd text_to_video
python test_simple.py
```

Generates video in `text_to_video/output/` directory.

### 3. Simple API: `api.py`
**File:** `text_to_video/api.py`

FastAPI endpoint that wraps the function:
```bash
python -m uvicorn text_to_video.api:app --host 0.0.0.0 --port 8000
```

Then POST to:
```
POST /generate
{
  "job_description": "Your job description...",
  "output_path": "/path/to/output",
  "output_name": "video_name"
}
```

### 4. Documentation: `SIMPLE_USAGE.md`
**File:** `text_to_video/SIMPLE_USAGE.md`

Simple usage guide with examples.

## How It Works

1. **No file reading** - Takes text directly, not from `job_description.txt`
2. **All outputs go to output_path** - script.json, audio files, video all in one place
3. **Three steps built-in**:
   - Step 1: Generate script (LLM)
   - Step 2: Generate audio (TTS)
   - Step 3: Generate video (FFmpeg)

## Output Structure

```
/your/output/path/
├── script.json        # Generated dialogue script
├── audio/
│   ├── character_0_0.mp3
│   ├── character_1_0.mp3
│   └── ... (one per dialogue segment)
└── video_name.mp4     # Final video
```

## Quick Start

### Python Function
```python
from text_to_video.main import generate_video_from_text

video_path = generate_video_from_text(
    job_description="Senior Python Developer - 5+ years required",
    output_path="/tmp/job_videos"
)
```

### API Endpoint
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Developer...",
    "output_path": "/tmp/job_videos"
  }'
```

## Files Summary

| File | Purpose |
|------|---------|
| `main.py` | Contains `generate_video_from_text()` function |
| `api.py` | FastAPI wrapper endpoint |
| `test_simple.py` | Example usage |
| `SIMPLE_USAGE.md` | Documentation |

## Next Steps

1. **Test the function**:
   ```bash
   cd text_to_video
   python test_simple.py
   ```

2. **Or test the API**:
   ```bash
   python -m uvicorn text_to_video.api:app --host 0.0.0.0 --port 8000
   ```

3. **Or import in your backend**:
   ```python
   from text_to_video.main import generate_video_from_text
   ```

That's it! Simple, clean, no complex wrappers.
