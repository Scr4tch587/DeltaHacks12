# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated short-form video generator: LLM writes dialogue → Fish.audio TTS → FFmpeg composites video with dynamic captions and character images. Currently uses Family Guy characters (Stewie/Chris) for educational content.

## Architecture

**1. Script Generation** (`script_generator.py`)
- Uses `clients/openrouter_client.py` for API communication
- Uses `prompts/script_prompt_builder.py` for prompt construction
- Uses `utils/cache.py` for caching
- OpenRouter API → LLM generates dialogue with emotion markers + image selection → JSON output
- Cache: `cache/<topic>/scripts/script.json`

**2. Text-to-Speech** (`tts_generator.py`)
- Uses `clients/fish_audio_client.py` for API communication
- Uses `utils/cache.py` for caching
- Fish.audio API converts text (with emotion markers) → MP3 per line
- Cache: `cache/<topic>/audio/{character}_{line_index}.mp3`

**3. Video Composition** (`video_composer_ffmpeg.py`)
- Uses `video/transcription.py` for Whisper word-level timestamps
- Uses `video/subtitles.py` for ASS subtitle generation
- Uses `video/character_timing.py` for character image timing
- Uses `video/ffmpeg_builder.py` for FFmpeg command construction
- Uses `utils/media_utils.py` for media operations
- FFmpeg composites background + character images (timed via Whisper) + ASS subtitles + title → 1080x1920 MP4
- Output: `cache/<topic>/video/video_TIMESTAMP.mp4`

**Configuration** (`config.py`)
Character definitions, `get_available_images()` for image discovery, `get_topic_dirs()` for cache structure, styling constants

**Utilities** (`utils/`)
- `text_processing.py`: Emotion marker stripping, sentence splitting
- `media_utils.py`: FFmpeg checks, audio/video duration calculations
- `cache.py`: Generic caching functions for scripts, audio, timestamps

## Usage

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env  # Add OPENROUTER_API_KEY and FISH_AUDIO_API_KEY

# Full pipeline
python main.py --topic "quantum physics"

# Individual steps: --step {script|tts|video|all}
python main.py --topic "topic" --step video  # Reuses cached script/audio

# Force regeneration (bypass cache, useful after prompt changes)
python main.py --topic "topic" --force-regenerate
```

## Key Concepts

### Caching
Topic-based caching under `cache/<topic>/`: scripts (JSON), audio (MP3s), video output. Use `--force-regenerate` when changing prompts.

### Script Format
LLM generates JSON with emotion markers and image selection per sentence:
```json
{
  "lines": [{
    "character": "stewie",
    "text": "(confident) Text here. (excited) More text.",
    "images": ["smirking_stewie", "exasperated_stewie"]
  }]
}
```

### Emotions
Fish.audio recognizes `(emotion) text` format (e.g., `(confident) Hello!`). Available in `config.py:AVAILABLE_EMOTIONS`. Stripped from captions.

### Image Variants
Each character has multiple PNG variants in `assets/characters/{name}/`. LLM selects per sentence. Video composer uses Whisper word timestamps to sync image changes with sentence boundaries. Requires `default.png` fallback.

## Assets

- **Character Images**: `assets/characters/{name}/` with `default.png` + variant PNGs (transparency supported)
- **Backgrounds**: MP4/MOV/AVI in `assets/backgrounds/` (uses first found, loops, resizes to 9:16)

## API Keys

- **OpenRouter**: Script generation (~$0.01-0.05/script) - set in `.env`
- **Fish.audio**: TTS (~$0.05-0.10/line) - set in `.env`

## File Structure

```
PeterCS/
├── src/
│   ├── config.py                      # Configuration, image discovery, topic dirs
│   ├── script_generator.py            # Script generation orchestrator
│   ├── tts_generator.py               # TTS generation orchestrator
│   ├── video_composer_ffmpeg.py      # Video composition orchestrator
│   ├── clients/                       # API client modules
│   │   ├── openrouter_client.py      # OpenRouter API wrapper
│   │   └── fish_audio_client.py       # Fish.audio API wrapper
│   ├── prompts/                       # Prompt building modules
│   │   └── script_prompt_builder.py   # LLM prompt construction
│   ├── utils/                         # Shared utilities
│   │   ├── text_processing.py         # Text manipulation (emotion stripping, sentence splitting)
│   │   ├── media_utils.py             # Media operations (FFmpeg, duration)
│   │   └── cache.py                   # Caching utilities
│   └── video/                         # Video processing modules
│       ├── transcription.py           # Whisper transcription for word timestamps
│       ├── subtitles.py               # ASS subtitle generation
│       ├── character_timing.py        # Character image timing calculations
│       └── ffmpeg_builder.py          # FFmpeg command construction
├── assets/
│   ├── characters/{name}/             # Character PNGs (default.png + variants)
│   └── backgrounds/                   # Background videos
├── cache/{topic}/                     # Topic-based caching
│   ├── scripts/script.json
│   ├── audio/{character}_{idx}.mp3
│   └── video/video_TIMESTAMP.mp4
├── main.py                            # CLI orchestrator
└── .env                               # API keys
```

## Development

**Modify prompts**: Edit `prompts/script_prompt_builder.py` → `--force-regenerate`
**Modify styling**: Edit constants in `config.py` → `--step video` (fast, reuses cached audio)
**Add characters**: Add to `CHARACTERS` dict in config.py + create `assets/characters/{name}/` with PNGs (including `default.png`)
**Debug**: FFmpeg stderr shows errors. Rendering: ~2-5min + Whisper transcription (~30-60s, cached)

**Module Organization**:
- **API Clients** (`clients/`): Isolated API communication logic
- **Prompts** (`prompts/`): All prompt building and templates
- **Utilities** (`utils/`): Reusable functions (text processing, media, caching)
- **Video Processing** (`video/`): Specialized video composition modules
- **Main Generators**: Orchestration only, delegate to specialized modules

**Backward compatibility**: Code handles old segment-based script format. Current format: one audio per line with images array.
