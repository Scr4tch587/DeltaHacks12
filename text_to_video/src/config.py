"""Configuration and constants for the Family Guy content generator."""

import os
from pathlib import Path

# Try to load environment variables from .env file if dotenv is available

from dotenv import load_dotenv
load_dotenv()


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
CHARACTERS_DIR = ASSETS_DIR / "characters"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
CACHE_DIR = PROJECT_ROOT / "cache"

# Ensure base cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_available_images(character: str) -> list[str]:
    """
    Get available image options for a character.

    Scans the character's subdirectory for available image variants.
    Excludes the "default" image from the returned list.

    Args:
        character: Character name (e.g., "stewie", "chris")

    Returns:
        List of available image names (without .png extension), sorted alphabetically
    """
    character_dir = CHARACTERS_DIR / character

    if not character_dir.exists():
        return []

    # Find all .png files in the character directory
    image_files = sorted(character_dir.glob("*.png"))

    # Extract image names (filename without .png), exclude "default"
    images = [f.stem for f in image_files if f.stem != "default"]

    return images


def get_topic_dirs(topic: str):
    """
    Get topic-specific directories for organized caching.

    Args:
        topic: The topic name or job description text

    Returns:
        Dictionary with topic_root, scripts, audio, and video paths
    """
    import hashlib
    import re
    
    # For job descriptions, extract first line and sanitize it
    # Remove newlines and get first meaningful line
    first_line = topic.split('\n')[0].strip() if '\n' in topic else topic.strip()
    
    # Create a clean slug - remove all invalid filename characters
    # Windows invalid chars: < > : " | ? * \ / and newlines
    topic_slug = re.sub(r'[<>:"|?*\\/\n\r]', '', first_line)  # Remove invalid chars first
    topic_slug = re.sub(r'[^\w\s-]', '', topic_slug)  # Keep only alphanumeric, spaces, hyphens, underscores
    topic_slug = re.sub(r'[-\s]+', '_', topic_slug)  # Replace spaces and hyphens with underscores
    topic_slug = topic_slug.strip('_')[:50]  # Limit length and remove leading/trailing underscores
    
    # If slug is empty or too short, use hash
    if not topic_slug or len(topic_slug) < 5:
        topic_hash = hashlib.md5(topic.encode('utf-8')).hexdigest()[:12]
        topic_slug = f"job_{topic_hash}"
    else:
        # Add hash suffix for uniqueness (in case multiple jobs have similar titles)
        topic_hash = hashlib.md5(topic.encode('utf-8')).hexdigest()[:8]
        topic_slug = f"{topic_slug}_{topic_hash}"

    topic_root = CACHE_DIR / topic_slug

    dirs = {
        'topic_root': topic_root,
        'scripts': topic_root / 'scripts',
        'audio': topic_root / 'audio',
        'video': topic_root / 'video'
    }

    # Create all directories
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    return dirs

# API Configuration
# OpenRouter API Key - can be set via environment variable or hardcoded here
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
# Fish Audio API Key - can be set via environment variable or hardcoded here
FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "8d892f2b7da94ab1b92c274b71be3296")

# Fish.audio API
FISH_AUDIO_URL = "https://api.fish.audio/v1/tts"

# Character Configuration
CHARACTERS = {
    "stewie": {
        "name": "Stewie Griffin",
        "voice_id": "e91c4f5974f149478a35affe820d02ac",
        "role": "teacher",
        "caption_color": "#FF6B6B",  # Red
        "caption_style": "bold"
    },
    "chris": {
        "name": "Chris Griffin",
        "voice_id": "d27226b55ea44a008fc5c608de497616",
        "role": "student",
        "caption_color": "#4ECDC4",  # Teal
        "caption_style": "normal"
    },
    "trump": {
        "name": "Donald Trump",
        "voice_id": "5196af35f6ff4a0dbf541793fc9f2157",
        "role": "recruiter",
        "caption_color": "#FFD700",  # Gold
        "caption_style": "bold"
    },
    "biden": {
        "name": "Joe Biden",
        "voice_id": "088c006b1f8949e0aa1f7a11af35f6e4",
        "role": "candidate",
        "caption_color": "#4169E1",  # Royal Blue
        "caption_style": "normal"
    },
    "obama": {
        "name": "Barack Obama",
        "voice_id": "4ce7e917cedd4bc2bb2e6ff3a46acaa1",
        "role": "candidate",
        "caption_color": "#1E90FF",  # Dodger Blue
        "caption_style": "normal"
    },
    "peter": {
        "name": "Peter Griffin",
        "voice_id": "a5c5987257a14018a90111ee52a4e71a",
        "role": "recruiter",
        "caption_color": "#FF6347",  # Tomato
        "caption_style": "bold"
    },
    "brian": {
        "name": "Brian Griffin",
        "voice_id": "df7b23b4d67c4340be1170ae6cbc2913",
        "role": "candidate",
        "caption_color": "#9370DB",  # Medium Purple
        "caption_style": "normal"
    },
    "spongebob": {
        "name": "SpongeBob SquarePants",
        "voice_id": "54e3a85ac9594ffa83264b8a494b901b",
        "role": "recruiter",
        "caption_color": "#FFD700",  # Yellow
        "caption_style": "bold"
    },
    "patrick": {
        "name": "Patrick Star",
        "voice_id": "d1520b60870b4e9aa01eab5bfefb1c45",
        "role": "candidate",
        "caption_color": "#FF69B4",  # Hot Pink
        "caption_style": "normal"
    }
}

# Video Configuration
VIDEO_WIDTH = 540
VIDEO_HEIGHT = 960  # 9:16 aspect ratio for shorts
VIDEO_FPS = 24
VIDEO_DURATION_TARGET = 30  # Target 5 minutes max

# Caption Configuration
CAPTION_FONT_SIZE = 70  # Reduced from 110 for smaller captions
CAPTION_FONT_FAMILY = "Nunito"
CAPTION_FONT_WEIGHT = 900  # Black (400=normal, 700=bold, 900=black)
CAPTION_POSITION = "center"  # Center horizontally, positioned above characters
CAPTION_VERTICAL_POS = 850  # Pixels from top (above characters)
CAPTION_MAX_WIDTH_PERCENT = 0.80  # Maximum 80% of screen width
CAPTION_STROKE_WIDTH = 3  # Reduced stroke width for smaller font
CAPTION_STROKE_COLOR = "black"

# Title Configuration
TITLE_DURATION = 2.5  # Seconds to display title
TITLE_FONT_SIZE = 200
TITLE_FONT_FAMILY = "Nunito"
TITLE_FONT_WEIGHT = 900  # Black (400=normal, 700=bold, 900=black)
TITLE_COLOR = "white"
TITLE_STROKE_WIDTH = 9  # Scaled with font
TITLE_FADE_DURATION = 0.5  # Seconds for fade in/out

# Character Image Configuration
# Characters should be 1/3 of screen height (1920 / 3 = 640)
CHARACTER_SIZE = (300, 300)  # Width, Height - 1/3 of screen height
CHARACTER_BOTTOM_MARGIN = 50  # Pixels from bottom of screen
CHARACTER_EDGE_MARGIN = 100  # Pixels from left/right edge of screen (increased for more side positioning)
CHARACTER_FADE_DURATION = 0.3  # Seconds for fade in/out when changing

# Character Group Color Tints (for visual distinction)
# Each character group gets a unique color tint applied to their images
CHARACTER_GROUP_COLORS = {
    "Trump+Biden": "#FF6B6B",  # Red tint
    "Trump+Obama": "#FFD700",  # Gold tint
    "Trump+Obama+Biden": "#FF8C00",  # Dark Orange tint
    "Stewie Griffin+Chris Griffin": "#4ECDC4",  # Teal tint
    "Peter Griffin+Stewie Griffin": "#9370DB",  # Medium Purple tint
    "Peter Griffin+Brian Griffin": "#FF6347",  # Tomato tint
    "Spongebob+Patrick": "#FFD700",  # Yellow tint
}

# Emotion Configuration for Fish Audio TTS
# Fish Audio supports 64+ emotions. These are the most useful for educational content.
# Format: Add emotion markers at the start of sentences: (emotion) text here
AVAILABLE_EMOTIONS = [
    # Basic emotions
    "happy", "sad", "angry", "excited", "calm", "surprised",
    # Educational/teaching appropriate
    "confident", "curious", "interested", "satisfied", "proud",
    # Character-appropriate
    "sarcastic",  # For Stewie's condescending tone
    "confused",   # For Chris's questions
    "frustrated", # For Stewie when Chris doesn't understand
    "grateful",   # For positive interactions
    # Tones and effects
    "whispering", "shouting", "laughing", "sighing",
]


# OpenRouter Configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Gemini 3 Flash Preview model
DEFAULT_MODEL = "google/gemini-3-flash-preview"
# Note: OPENROUTER_API_KEY is defined above in API Configuration section
