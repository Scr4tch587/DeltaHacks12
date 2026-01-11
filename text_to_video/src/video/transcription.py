"""Whisper transcription for word-level timestamps."""

import json
import threading
from pathlib import Path
from typing import Dict, List, Tuple

import stable_whisper

from utils.cache import load_timestamp_cache, save_timestamp_cache
from utils.text_processing import strip_emotion_markers


class Transcriber:
    """Handles Whisper transcription for word-level timestamps."""

    def __init__(self):
        self.whisper_model = None
        self._whisper_lock = threading.Lock()
        self._transcription_cache = {}

    def _load_whisper_model(self):
        """Load Whisper model in a thread-safe manner."""
        if self.whisper_model is None:
            with self._whisper_lock:
                if self.whisper_model is None:
                    print("Loading Whisper model (one-time, may take a moment)...")
                    self.whisper_model = stable_whisper.load_model('tiny')
        return self.whisper_model

    def _transcribe_single_audio(
        self,
        audio_path: Path,
        text: str,
        cache_path: Path
    ) -> Tuple[Path, List[Dict]]:
        """
        Transcribe a single audio file. Used for parallel processing.
        
        Returns:
            Tuple of (audio_path, word_timings)
        """
        # Check cache first
        cached = load_timestamp_cache(cache_path)
        if cached is not None:
            return audio_path, cached
        
        try:
            # Load Whisper model (thread-safe)
            model = self._load_whisper_model()
            
            # Transcribe with word-level timestamps
            print(f"Transcribing {audio_path.name} for precise word timing...")
            result = model.transcribe(
                str(audio_path),
                word_timestamps=True,
                regroup=True,
                language='en'
            )
            
            # Extract word-level timing
            words = []
            for segment in result.segments:
                for word in segment.words:
                    words.append({
                        'word': word.word.strip(),
                        'start': word.start,
                        'end': word.end
                    })
            
            # Cache the results
            save_timestamp_cache(cache_path, words)
            
            return audio_path, words
            
        except Exception as e:
            print(f"Warning: Could not use Whisper for precise timing of {audio_path.name} ({e})")
            print("  Falling back to estimated word timing")
            return audio_path, []

    def get_word_timestamps(
        self,
        audio_path: Path,
        text: str,
        cache_path: Path
    ) -> List[Dict]:
        """
        Get word-level timestamps using Whisper with stable-ts.
        Cache results to avoid re-transcribing.
        Falls back to simple division if Whisper unavailable.
        
        This method checks the parallel transcription cache first.
        
        Returns timestamps from Whisper (may not match script text exactly).
        """
        # Check parallel transcription cache first
        if audio_path in self._transcription_cache:
            return self._transcription_cache[audio_path]
        
        # Check file cache
        cached = load_timestamp_cache(cache_path)
        if cached is not None:
            self._transcription_cache[audio_path] = cached
            return cached
        
        # If not in cache, transcribe synchronously (fallback)
        _, result = self._transcribe_single_audio(audio_path, text, cache_path)
        self._transcription_cache[audio_path] = result
        return result

    def transcribe_all_audio_parallel(
        self,
        audio_files: List[Dict],
        output_dir: Path
    ) -> Dict[Path, List[Dict]]:
        """
        Transcribe all audio files sequentially.

        Args:
            audio_files: List of audio info dicts with 'audio_path' and 'text' keys
            output_dir: Directory for timestamp cache files

        Returns:
            Dictionary mapping audio_path -> word_timings
        """
        # Prepare transcription tasks
        tasks = []
        for audio_info in audio_files:
            audio_path = audio_info["audio_path"]
            text = strip_emotion_markers(audio_info.get("text", ""))
            cache_path = output_dir / f"{audio_path.stem}_timestamps.json"
            tasks.append((audio_path, text, cache_path))

        # Filter out tasks that are already cached
        tasks_to_process = []
        for audio_path, text, cache_path in tasks:
            cached = load_timestamp_cache(cache_path)
            if cached is not None:
                # Load from cache
                self._transcription_cache[audio_path] = cached
            else:
                tasks_to_process.append((audio_path, text, cache_path))

        if not tasks_to_process:
            print("All audio files already transcribed (using cache).")
            return self._transcription_cache

        print(f"Transcribing {len(tasks_to_process)} audio file(s)...")

        # Load model before processing (ensures it's loaded once)
        self._load_whisper_model()

        # Transcribe sequentially
        for audio_path, text, cache_path in tasks_to_process:
            try:
                result_path, word_timings = self._transcribe_single_audio(audio_path, text, cache_path)
                self._transcription_cache[result_path] = word_timings
            except Exception as e:
                print(f"Error transcribing {audio_path.name}: {e}")
                self._transcription_cache[audio_path] = []

        print(f"Completed transcription of {len(tasks_to_process)} audio file(s).")
        return self._transcription_cache

