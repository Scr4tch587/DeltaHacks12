"""Media utilities for FFmpeg and duration calculations."""

import subprocess
from pathlib import Path


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_audio_duration(audio_path: Path) -> float:
    """
    Get duration of an audio file using FFprobe.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Duration in seconds
        
    Raises:
        FileNotFoundError: If audio file doesn't exist
        RuntimeError: If FFprobe fails or returns invalid duration
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    try:
        duration = float(result.stdout.strip())
        if duration <= 0:
            raise ValueError(f"Invalid duration: {duration}")
        return duration
    except (ValueError, AttributeError) as e:
        raise RuntimeError(f"Failed to get duration for {audio_path}: {e}")


def get_video_duration(video_path: Path) -> float:
    """
    Get duration of a video file using FFprobe.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Duration in seconds
        
    Raises:
        FileNotFoundError: If video file doesn't exist
        RuntimeError: If FFprobe fails or returns invalid duration
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    try:
        duration = float(result.stdout.strip())
        if duration <= 0:
            raise ValueError(f"Invalid duration: {duration}")
        return duration
    except (ValueError, AttributeError) as e:
        raise RuntimeError(f"Failed to get duration for {video_path}: {e}")

