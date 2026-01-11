"""Caching utilities for scripts, audio, and timestamps."""

import json
from pathlib import Path
from typing import Dict, Optional


def load_script_cache(cache_path: Path) -> Optional[Dict]:
    """Load script from cache if it exists."""
    if cache_path.exists():
        print(f"Loading script from cache: {cache_path}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_script_cache(cache_path: Path, script: Dict):
    """Save script to cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    print(f"Script saved to cache: {cache_path}")


def check_audio_cache(cache_path: Path) -> Optional[Path]:
    """Check if audio exists in cache."""
    if cache_path.exists():
        print(f"Loading audio from cache: {cache_path}")
        return cache_path
    return None


def load_timestamp_cache(cache_path: Path) -> Optional[list]:
    """Load timestamp cache if it exists."""
    if cache_path.exists():
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_timestamp_cache(cache_path: Path, timestamps: list):
    """Save timestamp cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(timestamps, f, indent=2)

