"""Character image timing calculations."""

from pathlib import Path
from typing import Dict, List, Tuple

from config import CHARACTERS_DIR
from utils.text_processing import strip_emotion_markers, split_into_sentences
from utils.media_utils import get_audio_duration


class CharacterTimingCalculator:
    """Calculates timing for character image appearances."""

    def __init__(self, transcriber):
        """
        Initialize character timing calculator.
        
        Args:
            transcriber: Transcriber instance for getting word timestamps
        """
        self.transcriber = transcriber

    def _get_character_image_path(self, character: str, image: str) -> Path:
        """
        Get the path to a character's image variant.

        Falls back to default.png if the image variant doesn't exist.

        Args:
            character: Character name (e.g., "biden", "obama", "trump")
            image: Image variant name (e.g., "confident_obama", "surprised_biden")

        Returns:
            Path to the image file
        """
        character_dir = CHARACTERS_DIR / character
        image_path = character_dir / f"{image}.png"

        # If image variant exists, use it
        if image_path.exists():
            return image_path

        # Fall back to default
        default_path = character_dir / "default.png"
        if default_path.exists():
            return default_path

        # If neither exists, raise error (images should be set up before generation)
        raise FileNotFoundError(
            f"No image found for character '{character}' image variant '{image}' "
            f"and no default.png in {character_dir}"
        )

    def calculate_image_timings(
        self,
        audio_files: List[Dict],
        output_dir: Path
    ) -> Tuple[Dict[str, Dict[str, List[Tuple[float, float]]]], Dict[str, Dict[str, Path]]]:
        """
        Calculate timing for character image appearances based on sentence timing.
        Now returns DYNAMIC character data based on who's actually in the script.
        
        Args:
            audio_files: List of audio info dicts with 'audio_path', 'text', 'images', 'character'
            output_dir: Directory for timestamp cache files
            
        Returns:
            Tuple of:
            - character_image_times: Dict[character_name][image_name] -> list of (start, end) tuples
            - character_image_paths: Dict[character_name][image_name] -> Path
        """
        # Dynamic structure: character_name -> {image_name -> [(start, end), ...]}
        character_image_times = {}
        character_image_paths = {}

        # Process audio files - map images to sentences within each line
        current_time = 0.0
        for audio_info in audio_files:
            duration = get_audio_duration(audio_info["audio_path"])
            character = audio_info["character"]
            text = audio_info.get("text", "")
            images = audio_info.get("images", [])
            
            # Initialize this character if not seen before
            if character not in character_image_times:
                character_image_times[character] = {}
            if character not in character_image_paths:
                character_image_paths[character] = {}
            
            # Split text into sentences
            sentences = split_into_sentences(text)
            
            # Get word timestamps for this audio file to determine sentence timing
            text_for_display = strip_emotion_markers(text)
            timestamp_cache = output_dir / f"{audio_info['audio_path'].stem}_timestamps.json"
            word_timings = self.transcriber.get_word_timestamps(
                audio_info["audio_path"], text_for_display, timestamp_cache
            )
            
            # If we have word timings, use them to determine sentence boundaries
            if word_timings and len(sentences) > 0:
                # Map words to sentences
                words = [w['word'] for w in word_timings]
                word_text = ' '.join(words).lower()
                
                # Find sentence boundaries in word timings
                sentence_starts = []
                sentence_ends = []
                word_idx = 0
                
                for sentence_idx, sentence in enumerate(sentences):
                    sentence_words = sentence.lower().split()
                    if not sentence_words:
                        continue
                    
                    # Find where this sentence starts in word_timings
                    sentence_start_idx = None
                    for i in range(word_idx, len(word_timings)):
                        # Try to match sentence start
                        if word_timings[i]['word'].lower().strip('.,!?') == sentence_words[0].strip('.,!?'):
                            sentence_start_idx = i
                            break
                    
                    if sentence_start_idx is not None:
                        sentence_starts.append(word_timings[sentence_start_idx]['start'])
                        # Find end of sentence (start of next sentence or end of audio)
                        if sentence_idx < len(sentences) - 1:
                            next_sentence_words = sentences[sentence_idx + 1].lower().split()
                            if next_sentence_words:
                                # Find start of next sentence
                                for i in range(sentence_start_idx + 1, len(word_timings)):
                                    if word_timings[i]['word'].lower().strip('.,!?') == next_sentence_words[0].strip('.,!?'):
                                        sentence_ends.append(word_timings[i]['start'])
                                        word_idx = i
                                        break
                                else:
                                    # Next sentence not found, use end of audio
                                    sentence_ends.append(duration)
                                    word_idx = len(word_timings)
                            else:
                                sentence_ends.append(duration)
                                word_idx = len(word_timings)
                        else:
                            # Last sentence
                            sentence_ends.append(duration)
                    else:
                        # Fallback: divide evenly
                        time_per_sentence = duration / len(sentences)
                        sentence_starts.append(sentence_idx * time_per_sentence)
                        sentence_ends.append((sentence_idx + 1) * time_per_sentence)
            else:
                # Fallback: divide duration evenly among sentences
                if len(sentences) > 0:
                    time_per_sentence = duration / len(sentences)
                    sentence_starts = [i * time_per_sentence for i in range(len(sentences))]
                    sentence_ends = [(i + 1) * time_per_sentence for i in range(len(sentences))]
                else:
                    sentence_starts = [0]
                    sentence_ends = [duration]
            
            # Assign images to sentences for this character's speaking time
            # IMPORTANT: Ensure images don't overlap by using sequential assignment
            if images and len(images) > 0:
                # If we have specific images, assign each to its sentence (no overlap)
                for i, (sentence_start, sentence_end) in enumerate(zip(sentence_starts, sentence_ends)):
                    image = images[i % len(images)]  # Cycle through images
                    
                    # Add time range for this image (sequential, non-overlapping)
                    if image not in character_image_times[character]:
                        character_image_times[character][image] = []
                    
                    # Append this time range (these will be sequential within a line)
                    character_image_times[character][image].append((current_time + sentence_start, current_time + sentence_end))
            else:
                # No specific images provided, use default image for entire duration
                default_image = "default"
                if default_image not in character_image_times[character]:
                    character_image_times[character][default_image] = []
                character_image_times[character][default_image].append((current_time, current_time + duration))

            current_time += duration

        # Merge overlapping time ranges for each image to prevent rendering multiple variants simultaneously
        def merge_time_ranges(time_ranges: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
            """Merge overlapping or adjacent time ranges."""
            if not time_ranges:
                return []

            # Sort by start time
            sorted_ranges = sorted(time_ranges)
            merged = [sorted_ranges[0]]

            for current_start, current_end in sorted_ranges[1:]:
                last_start, last_end = merged[-1]

                # If current range overlaps or is adjacent to last range, merge them
                if current_start <= last_end:  # Overlapping or touching
                    merged[-1] = (last_start, max(last_end, current_end))
                else:
                    merged.append((current_start, current_end))

            return merged

        # Apply merging to all image time ranges for all characters
        # BUT: Don't merge if it would cause overlaps within the same character
        for character in character_image_times:
            # First, sort all images by their earliest appearance
            char_images = sorted(
                character_image_times[character].items(),
                key=lambda x: min(t[0] for t in x[1]) if x[1] else float('inf')
            )
            
            # Process each image's time ranges
            processed = {}
            for image, time_ranges in char_images:
                # Merge overlapping ranges for this specific image
                merged = merge_time_ranges(time_ranges)
                
                # Now check against other images for this character to prevent overlaps
                final_ranges = []
                for start, end in merged:
                    # Check if this range overlaps with any already-processed image ranges
                    conflict = False
                    for other_image, other_ranges in processed.items():
                        for other_start, other_end in other_ranges:
                            # Check for overlap
                            if start < other_end and end > other_start:
                                # There's an overlap - we need to clip this range
                                # Keep the earlier image (already processed) and clip the current one
                                if start >= other_start and end <= other_end:
                                    # Fully contained - skip this range entirely
                                    conflict = True
                                    break
                                elif start < other_start and end > other_end:
                                    # Current range contains other - split into two parts
                                    # Before the overlap
                                    if start < other_start:
                                        final_ranges.append((start, other_start))
                                    # After the overlap
                                    if end > other_end:
                                        final_ranges.append((other_end, end))
                                    conflict = True
                                    break
                                elif start < other_start:
                                    # Overlap at the end - clip the end
                                    final_ranges.append((start, other_start))
                                    conflict = True
                                    break
                                else:
                                    # Overlap at the start - clip the start
                                    if end > other_end:
                                        final_ranges.append((other_end, end))
                                    conflict = True
                                    break
                        if conflict:
                            break
                    
                    if not conflict:
                        final_ranges.append((start, end))
                
                # Merge the final ranges again (in case clipping created adjacent ranges)
                processed[image] = merge_time_ranges(final_ranges) if final_ranges else []
            
            character_image_times[character] = processed

        # Get image paths for each character's images
        for character in character_image_times:
            for image in character_image_times[character].keys():
                try:
                    path = self._get_character_image_path(character, image)
                    character_image_paths[character][image] = path
                except FileNotFoundError as e:
                    print(f"Warning: {e}")
                    # Try to use default image
                    try:
                        default_path = self._get_character_image_path(character, "default")
                        character_image_paths[character][image] = default_path
                    except FileNotFoundError:
                        print(f"Error: No default image for character '{character}'")
                        raise

        return character_image_times, character_image_paths
