# PeterCS - Family Guy Educational Short-Form Content Generator

An automated pipeline that generates engaging educational videos featuring Family Guy characters (Stewie and Chris) discussing complex topics with word-by-word karaoke-style captions.

## Features

-   **AI-Generated Scripts**: Uses Google Gemini to generate witty educational dialogue
-   **Character Voice Synthesis**: Fish.audio TTS API for authentic character voices
-   **Karaoke-Style Captions**: Word-by-word highlighting synchronized with speech
-   **Professional Video Composition**: FFmpeg-based rendering for reliability and quality
-   **Topic-Based Organization**: Organized cache structure with dedicated folders per topic

## Project Structure

```
PeterCS/
├── src/
│   ├── config.py                      # Configuration and constants
│   ├── script_generator.py            # Script generation orchestrator
│   ├── tts_generator.py               # TTS generation orchestrator
│   ├── video_composer_ffmpeg.py      # Video composition orchestrator
│   ├── clients/                       # API client modules
│   │   ├── gemini_client.py          # Gemini API wrapper
│   │   └── fish_audio_client.py       # Fish.audio API wrapper
│   ├── prompts/                       # Prompt building modules
│   │   └── script_prompt_builder.py   # LLM prompt construction
│   ├── utils/                         # Shared utilities
│   │   ├── text_processing.py         # Text manipulation utilities
│   │   ├── media_utils.py             # Media operation utilities
│   │   └── cache.py                   # Caching utilities
│   └── video/                         # Video processing modules
│       ├── transcription.py           # Whisper transcription
│       ├── subtitles.py               # Subtitle generation
│       ├── character_timing.py        # Character timing calculations
│       └── ffmpeg_builder.py          # FFmpeg command building
├── assets/
│   ├── characters/                    # Character PNG images
│   └── backgrounds/                   # Background videos
├── cache/
│   └── <topic_name>/                  # Topic-specific cache folders
│       ├── scripts/                   # JSON dialogue scripts
│       ├── audio/                     # MP3 character audio files
│       └── video/                     # Generated MP4 videos
├── requirements.txt
├── main.py                            # Main orchestrator CLI
└── CLAUDE.md                          # Development documentation
```

## Requirements

-   **Python 3.10+**
-   **FFmpeg** - Must be installed on your system:

    ```bash
    # Windows
    choco install ffmpeg
    # OR
    scoop install ffmpeg

    # Mac
    brew install ffmpeg

    # Linux
    sudo apt install ffmpeg
    ```

## Setup

1. **Create virtual environment and install dependencies:**

    ```bash
    uv venv
    .venv\Scripts\Activate.ps1  # Windows
    # or: source .venv/bin/activate  # Linux/Mac

    uv pip install -r requirements.txt
    ```

2. **Set up API keys:**
   Create a `.env` file:

    ```env
    GEMINI_API_KEY=your_gemini_api_key_here
    ```

    Fish.audio API key is included in `config.py`

3. **Add assets:**
    - Place character PNGs in `assets/characters/` (`stewie.png`, `chris.png`)
    - Place background video in `assets/backgrounds/` (e.g., `minecraft_parkour.mp4`)

## Usage

**Generate a complete video:**

```bash
python main.py --topic "quantum physics" --step all
```

**Run individual pipeline steps:**

```bash
# 1. Generate script only (costs ~$0.01-0.05)
python main.py --topic "artificial intelligence" --step script

# 2. Generate TTS audio (costs ~$0.10-0.20, requires cached script)
python main.py --topic "artificial intelligence" --step tts

# 3. Generate video (free, requires cached script and audio)
python main.py --topic "artificial intelligence" --step video
```

**Force regeneration (bypass cache):**

```bash
python main.py --topic "quantum physics" --step all --force-regenerate
```

**Custom output name:**

```bash
python main.py --topic "quantum physics" --output-name "my_video"
```

## Output

Videos are saved to `cache/<topic_name>/video/video_TIMESTAMP.mp4` with:

-   **Resolution**: 1080x1920 (9:16 vertical for TikTok/Shorts/Reels)
-   **Frame Rate**: 30 fps
-   **Video Codec**: H.264 (CRF 23, medium preset)
-   **Audio Codec**: AAC (192 kbps)
-   **Captions**: Karaoke-style word-by-word highlighting

## Features in Detail

### Karaoke Captions

-   Each word appears one at a time as it's spoken
-   Current word: bright white + bold
-   Previous words: 50% transparent
-   Future words: invisible
-   Character-specific colors (Stewie: yellow accent, Chris: cyan accent)

### Caching System

-   **Scripts**: `cache/<topic>/scripts/script.json`
-   **Audio**: `cache/<topic>/audio/{character}_{line_index}.mp3`
-   **Videos**: `cache/<topic>/video/video_TIMESTAMP.mp4`
-   Use `--force-regenerate` to bypass all caches

### Cost Breakdown

-   Script generation: Uses Google Gemini (gemini-3-flash-preview)
-   TTS generation: ~$0.10-0.20 per video (Fish.audio)
-   Video composition: Free (local FFmpeg processing)

## Development

See `CLAUDE.md` for detailed development documentation including:

-   Architecture overview
-   Modular structure and organization
-   Testing individual modules
-   Debugging tips
-   Future enhancements

### Code Organization

The codebase is modularized for maintainability:

- **`clients/`**: API client wrappers (Gemini, Fish.audio)
- **`prompts/`**: Prompt building and templates
- **`utils/`**: Reusable utilities (text processing, media operations, caching)
- **`video/`**: Video processing modules (transcription, subtitles, timing, FFmpeg)
- **Main generators**: Orchestration logic that delegates to specialized modules

## License

MIT
