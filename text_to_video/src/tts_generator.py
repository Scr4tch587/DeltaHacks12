"""Text-to-Speech generation using Fish.audio API with concurrent requests."""

import asyncio
from pathlib import Path
from typing import Dict, List
import aiohttp

# Handle nested event loops (when called from FastAPI/async context)
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass


def run_async(coro):
    """Run async coroutine, handling both sync and async contexts."""
    try:
        loop = asyncio.get_running_loop()
        # Already in an async context, create a new task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop, use asyncio.run
        return asyncio.run(coro)


from config import (
    FISH_AUDIO_API_KEY,
    FISH_AUDIO_URL,
    CHARACTERS,
    get_topic_dirs
)
from clients.fish_audio_client import FishAudioClient
from utils.cache import check_audio_cache
from utils.text_processing import strip_image_names_from_text


class TTSGenerator:
    """Generates audio from text using Fish.audio API with concurrent requests."""

    def __init__(self, api_key: str = FISH_AUDIO_API_KEY, topic: str = None, max_concurrent: int = 5):
        self.api_client = FishAudioClient(api_key=api_key, url=FISH_AUDIO_URL)
        self.topic = topic
        self.max_concurrent = max_concurrent  # Limit concurrent requests (5 for users under $100)

    def _get_cache_path(self, character: str, line_index: int) -> Path:
        """Generate cache file path for audio."""
        if not self.topic:
            raise ValueError("Topic must be set for TTSGenerator")
        topic_dirs = get_topic_dirs(self.topic)
        return topic_dirs['audio'] / f"{character}_{line_index}.mp3"

    def _load_from_cache(self, character: str, line_index: int) -> Path | None:
        """Check if audio exists in cache."""
        cache_path = self._get_cache_path(character, line_index)
        return check_audio_cache(cache_path)

    async def _generate_speech_async(
        self,
        session: aiohttp.ClientSession,
        text: str,
        character: str,
        line_index: int,
        force_regenerate: bool,
        semaphore: asyncio.Semaphore
    ) -> Dict:
        """
        Async helper to generate speech audio for a single line.
        
        Returns dict with audio_path and line info.
        """
        async with semaphore:  # Limit concurrent requests
            if character not in CHARACTERS:
                raise ValueError(f"Unknown character: {character}")

            # Check cache first
            if not force_regenerate:
                cached_audio = self._load_from_cache(character, line_index)
                if cached_audio:
                    return {
                        "character": character,
                        "text": text,
                        "audio_path": cached_audio,
                        "line_index": line_index
                    }

            # Generate new audio
            print(f"Generating audio for {character}: {text[:80]}...")

            voice_id = CHARACTERS[character]["voice_id"]
            output_path = self._get_cache_path(character, line_index)

            await self.api_client.generate_audio(
                session=session,
                text=text,
                voice_id=voice_id,
                output_path=output_path
            )

            print(f"Audio saved to: {output_path}")
            return {
                "character": character,
                "text": text,
                "audio_path": output_path,
                "line_index": line_index
            }

    def generate_speech(
        self,
        text: str,
        character: str,
        line_index: int = 0,
        force_regenerate: bool = False
    ) -> Path:
        """
        Generate speech audio for a full line of text (synchronous wrapper).

        Args:
            text: The full text to convert to speech (may contain emotion markers like "(emotion) text")
            character: Character name (must be in CHARACTERS config)
            line_index: Index of the line (for cache naming)
            force_regenerate: If True, bypass cache and regenerate

        Returns:
            Path to the generated audio file

        Note:
            Fish Audio automatically recognizes emotion markers in parentheses at the start
            of sentences. The text should already contain these markers.
        """
        # Use async implementation for single requests too
        return run_async(self._generate_single_speech_async(text, character, line_index, force_regenerate))

    async def _generate_single_speech_async(
        self,
        text: str,
        character: str,
        line_index: int,
        force_regenerate: bool
    ) -> Path:
        """Async helper for single speech generation."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        async with aiohttp.ClientSession() as session:
            result = await self._generate_speech_async(
                session, text, character, line_index, force_regenerate, semaphore
            )
            return result["audio_path"]

    def generate_script_audio(self, script: Dict, force_regenerate: bool = False) -> List[Dict]:
        """
        Generate audio for all lines in a script using concurrent requests.

        Args:
            script: Script dictionary with 'lines' key, where each line has 'text' and 'images'
            force_regenerate: If True, bypass cache and regenerate all

        Returns:
            List of audio info dictionaries:
            [
                {
                    "character": "stewie",
                    "text": "Full text with (emotion) markers...",
                    "images": ["happy", "happy", "sad"],
                    "audio_path": Path(...),
                    "line_index": 0
                },
                ...
            ]
        """
        # Use async implementation for concurrent generation
        return run_async(self._generate_script_audio_async(script, force_regenerate))

    async def _generate_script_audio_async(
        self,
        script: Dict,
        force_regenerate: bool = False
    ) -> List[Dict]:
        """
        Async implementation of generate_script_audio with concurrent requests.
        """
        # Prepare tasks for all lines
        line_data = []  # Store line metadata for results
        
        for line_index, line in enumerate(script["lines"]):
            character = line["character"]
            text = line.get("text", "")
            # Strip image names that were incorrectly placed in text (like "pretentious_brian")
            # Keep valid emotions (single words) but remove image names (with underscores)
            text = strip_image_names_from_text(text)
            images = line.get("images", [])
            
            # Handle backward compatibility with old format
            if "segments" in line:
                # Old format: combine segments into full text
                segments = line["segments"]
                text_parts = []
                images = []
                for segment in segments:
                    text_parts.append(segment.get("text", ""))
                    images.append(segment.get("image", "default"))
                text = " ".join(text_parts)
            
            if not text:
                continue

            line_data.append({
                "character": character,
                "text": text,
                "images": images,
                "line_index": line_index
            })

        # Create semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Create async tasks for all audio generation
        async with aiohttp.ClientSession() as session:
            tasks = [
                self._generate_speech_async(
                    session,
                    data["text"],
                    data["character"],
                    data["line_index"],
                    force_regenerate,
                    semaphore
                )
                for data in line_data
            ]
            
            # Execute all tasks concurrently (limited by semaphore)
            print(f"Generating {len(tasks)} audio files with max {self.max_concurrent} concurrent requests...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine results with line metadata
        audio_files = []
        for i, (result, data) in enumerate(zip(results, line_data)):
            if isinstance(result, Exception):
                print(f"Error generating audio for line {data['line_index']}: {result}")
                continue
            
            audio_files.append({
                "character": result["character"],
                "text": result["text"],
                "images": data["images"],
                "audio_path": result["audio_path"],
                "line_index": result["line_index"]
            })
        
        # Sort by line_index to maintain order
        audio_files.sort(key=lambda x: x["line_index"])
        
        return audio_files


if __name__ == "__main__":
    # Test the TTS generator
    test_topic = "test_tts"
    tts = TTSGenerator(topic=test_topic)

    # Test with Stewie
    stewie_audio = tts.generate_speech(
        "(confident) What the deuce? (frustrated) Chris, you blithering idiot, hand me the remote!",
        "stewie",
        0,
        force_regenerate=True
    )
    print(f"Stewie audio: {stewie_audio}")

    # Test with Chris
    chris_audio = tts.generate_speech(
        "(confused) Aw, come on Stewie, I was watching cartoons!",
        "chris",
        1,
        force_regenerate=True
    )
    print(f"Chris audio: {chris_audio}")
