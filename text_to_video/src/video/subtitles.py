"""Subtitle generation for video captions."""

from pathlib import Path
from typing import List, Dict, Tuple

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    CAPTION_FONT_SIZE,
    CAPTION_FONT_FAMILY,
    CAPTION_FONT_WEIGHT,
    CAPTION_VERTICAL_POS,
    CAPTION_MAX_WIDTH_PERCENT,
    CAPTION_STROKE_WIDTH,
    TITLE_DURATION,
    TITLE_FONT_SIZE,
    TITLE_FONT_FAMILY,
    TITLE_FONT_WEIGHT,
    TITLE_STROKE_WIDTH,
    TITLE_FADE_DURATION,
)
from utils.text_processing import strip_emotion_markers
from utils.media_utils import get_audio_duration


class SubtitleGenerator:
    """Generates ASS subtitle files with chunked text display."""

    def __init__(self, transcriber):
        """
        Initialize subtitle generator.
        
        Args:
            transcriber: Transcriber instance for getting word timestamps
        """
        self.transcriber = transcriber

    def _align_script_words_with_timestamps(
        self,
        script_words: List[str],
        whisper_timings: List[Dict],
        duration: float
    ) -> List[Dict]:
        """
        Align script words with Whisper timestamps.
        
        Uses Whisper timestamps for timing but script words for caption text.
        If word counts don't match, distributes timestamps proportionally.
        
        Args:
            script_words: List of words from the script (with emotion markers stripped)
            whisper_timings: List of word timing dicts from Whisper with 'word', 'start', 'end'
            duration: Total duration of the audio
            
        Returns:
            List of word timing dicts with script words but Whisper timestamps
        """
        if not whisper_timings:
            # No Whisper timings, use estimated timing
            time_per_word = duration / max(len(script_words), 1)
            return [
                {'word': w, 'start': i * time_per_word, 'end': (i + 1) * time_per_word}
                for i, w in enumerate(script_words)
            ]
        
        # Normalize words for comparison (lowercase, strip punctuation)
        def normalize_word(w):
            return w.lower().strip('.,!?;:')
        
        whisper_normalized = [normalize_word(w['word']) for w in whisper_timings]
        
        # Try to align script words with Whisper timestamps
        aligned = []
        whisper_idx = 0
        
        for script_idx, script_word in enumerate(script_words):
            script_norm = normalize_word(script_word)
            
            # Try to find matching Whisper word within a search window
            found_match = False
            search_window = min(5, len(whisper_timings) - whisper_idx)  # Expanded window for better matching
            
            for i in range(whisper_idx, whisper_idx + search_window):
                if whisper_normalized[i] == script_norm:
                    # Found match, use this timestamp
                    aligned.append({
                        'word': script_word,  # Use script word (preserves capitalization/punctuation)
                        'start': whisper_timings[i]['start'],
                        'end': whisper_timings[i]['end']
                    })
                    whisper_idx = i + 1
                    found_match = True
                    break
            
            if not found_match:
                # No match found, use next available timestamp or interpolate
                if whisper_idx < len(whisper_timings):
                    # Use next available timestamp
                    aligned.append({
                        'word': script_word,
                        'start': whisper_timings[whisper_idx]['start'],
                        'end': whisper_timings[whisper_idx]['end']
                    })
                    whisper_idx += 1
                else:
                    # Ran out of Whisper timings, interpolate from last timestamp
                    if aligned:
                        # Use last timestamp and distribute remaining time
                        last_end = aligned[-1]['end']
                        remaining_words = len(script_words) - script_idx
                        remaining_time = max(0, duration - last_end)
                        time_per_word = remaining_time / max(remaining_words, 1)
                        
                        aligned.append({
                            'word': script_word,
                            'start': last_end + (script_idx - len(aligned)) * time_per_word,
                            'end': last_end + (script_idx - len(aligned) + 1) * time_per_word
                        })
                    else:
                        # No aligned words yet, use estimated timing
                        time_per_word = duration / len(script_words)
                        aligned.append({
                            'word': script_word,
                            'start': script_idx * time_per_word,
                            'end': (script_idx + 1) * time_per_word
                        })
        
        # Ensure timestamps are in order and don't exceed duration
        # Remove words that start at or after duration (they won't be heard/seen)
        MIN_WORD_DISPLAY_TIME = 0.15  # Minimum 150ms for readability
        
        filtered_aligned = []
        for word_timing in aligned:
            if word_timing['start'] < duration:
                # Clamp end time but ensure visible duration
                if word_timing['end'] > duration:
                    word_timing['end'] = duration

                # Ensure minimum display time for readability
                min_end = word_timing['start'] + MIN_WORD_DISPLAY_TIME
                if word_timing['end'] < min_end:
                    word_timing['end'] = min(min_end, duration)

                filtered_aligned.append(word_timing)

        # Ensure last word extends to fill any gap before duration
        # This prevents the last word from appearing too briefly
        if filtered_aligned and filtered_aligned[-1]['end'] < duration:
            filtered_aligned[-1]['end'] = duration

        return filtered_aligned

    def _chunk_words(self, word_timings: List[Dict]) -> List[List[Dict]]:
        """
        Chunk words into groups that fit within CAPTION_MAX_WIDTH_PERCENT of screen width.
        Never allows text to wrap - chunks are cut before they would exceed the width.

        Args:
            word_timings: List of word timing dicts with 'word', 'start', 'end'

        Returns:
            List of word chunks, where each chunk is a list of word timing dicts
        """
        if not word_timings:
            return []

        # Estimate average character width as pixels (rough approximation for Arial bold at size 70)
        # This is approximate - ASS will handle actual rendering
        avg_char_width_px = CAPTION_FONT_SIZE * 0.6  # ~42px per character for bold Arial
        max_width_px = VIDEO_WIDTH * CAPTION_MAX_WIDTH_PERCENT

        chunks = []
        current_chunk = []
        current_width = 0

        for word_timing in word_timings:
            word = word_timing['word']
            # Add 1 for space between words
            word_width = len(word) * avg_char_width_px + avg_char_width_px  # +1 space

            # Check if adding this word would exceed max width
            if current_chunk and (current_width + word_width > max_width_px):
                # Save current chunk and start new one
                chunks.append(current_chunk)
                current_chunk = [word_timing]
                current_width = len(word) * avg_char_width_px
            else:
                # Add word to current chunk
                current_chunk.append(word_timing)
                current_width += word_width

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _format_ass_time(self, seconds: float) -> str:
        """Format seconds as ASS time format (H:MM:SS.CS)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def create_subtitle_file(
        self,
        audio_files: List[Dict],
        output_dir: Path,
        title: str
    ) -> Tuple[Path, List[Path]]:
        """
        Create an ASS subtitle file with chunked text display and title sequence.

        Args:
            audio_files: List of audio info dicts
            output_dir: Output directory for subtitle file
            title: Video title to display

        Returns:
            tuple: (subtitle_path, list of timestamp cache files created)
        """
        subtitle_path = output_dir / "subtitles.ass"
        timestamp_files = []  # Track timestamp cache files for cleanup

        # Calculate margin from bottom for proper vertical positioning
        # ASS MarginV is from bottom when Alignment is 2 (bottom-center)
        caption_margin_bottom = VIDEO_HEIGHT - CAPTION_VERTICAL_POS

        bold_value = -1 if CAPTION_FONT_WEIGHT >= 700 else 0
        title_bold = -1 if TITLE_FONT_WEIGHT >= 700 else 0

        # Dynamically get all unique characters from audio_files
        characters_in_script = list(set(audio_info["character"] for audio_info in audio_files))
        
        # Import CHARACTERS to get caption colors
        from config import CHARACTERS
        
        # ASS subtitle header with dynamically created styles for each character
        # Color format: &HAABBGGRR (alpha, blue, green, red in hex)
        # Title positioned at top (Alignment 8 = top center)
        ass_content = f"""[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
        
        # Add styles for each character dynamically
        for character in characters_in_script:
            # Get character color from config
            if character in CHARACTERS:
                char_color_hex = CHARACTERS[character].get("caption_color", "white")
            else:
                char_color_hex = "white"  # Fallback
            
            # Convert hex color to ASS format: &H00BBGGRR
            # ASS format: &HAABBGGRR (alpha, blue, green, red)
            # Hex format: #RRGGBB
            def hex_to_ass_color(hex_color: str) -> str:
                """Convert hex color (#RRGGBB) to ASS format (&H00BBGGRR)."""
                hex_color = hex_color.strip().lower()
                
                # Named colors map
                color_map = {
                    "white": "&H00FFFFFF",
                    "green": "&H0000FF00",
                    "yellow": "&H0000FFFF",
                    "red": "&H000000FF",
                    "blue": "&H00FF0000",
                    "cyan": "&H00FFFF00",
                    "magenta": "&H00FF00FF",
                    "orange": "&H0000A5FF",
                }
                
                # Check if it's a named color
                if hex_color in color_map:
                    return color_map[hex_color]
                
                # Parse hex color #RRGGBB
                if hex_color.startswith("#") and len(hex_color) == 7:
                    try:
                        r = int(hex_color[1:3], 16)
                        g = int(hex_color[3:5], 16)
                        b = int(hex_color[5:7], 16)
                        # ASS format: &H00BBGGRR (alpha=00, blue, green, red)
                        return f"&H00{b:02X}{g:02X}{r:02X}"
                    except ValueError:
                        pass
                
                # Fallback to white
                return "&H00FFFFFF"
            
            ass_color = hex_to_ass_color(char_color_hex)
            
            # Add regular style
            ass_content += f"Style: {character},Nunito-Black,{CAPTION_FONT_SIZE},{ass_color},&H00FFFFFF,&H00000000,&HFF000000,{bold_value},0,0,0,100,100,0,0,1,{CAPTION_STROKE_WIDTH},0,2,10,10,{caption_margin_bottom},1\n"
            
            # Add karaoke style (same as regular for word-by-word display)
            ass_content += f"Style: {character}_kara,Nunito-Black,{CAPTION_FONT_SIZE},{ass_color},&H00FFFFFF,&H00000000,&HFF000000,{bold_value},0,0,0,100,100,0,0,1,{CAPTION_STROKE_WIDTH},0,2,10,10,{caption_margin_bottom},1\n"
        
        # Add title style
        ass_content += f"Style: title,Nunito-Black,{TITLE_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&HFF000000,{title_bold},0,0,0,100,100,0,0,1,{TITLE_STROKE_WIDTH},0,8,10,10,100,1\n"
        
        ass_content += f"""
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Add title at top of screen (overlays with dialogue)
        # Use the provided title (LLM-generated)
        title_text = title.upper()
        # Estimate: Arial font width is roughly 0.6 * font_size per character
        # Use 80% of video width as max width, with some padding
        max_width = VIDEO_WIDTH * 0.8
        # Estimate character width (Arial is roughly 0.6x font size per char, but varies)
        # Use a conservative estimate: 0.55 * font_size per character for uppercase
        estimated_chars = len(title_text)
        if estimated_chars > 0:
            # Calculate font size: max_width / (chars * char_width_ratio)
            # Add some buffer for spacing and stroke
            calculated_font_size = int(max_width / (estimated_chars * 0.55))
            # Clamp between reasonable min and max sizes
            title_font_size = max(80, min(calculated_font_size, TITLE_FONT_SIZE))
        else:
            title_font_size = TITLE_FONT_SIZE
        
        title_start = self._format_ass_time(0)
        title_end = self._format_ass_time(TITLE_DURATION)
        # No fade in (0ms), fade out over TITLE_FADE_DURATION at the end
        fade_in_ms = 0
        fade_out_ms = int(TITLE_FADE_DURATION * 1000)
        # Override font size in the dialogue line using {\fs<size>} tag
        ass_content += f"Dialogue: 0,{title_start},{title_end},title,,0,0,0,,{{\\fad({fade_in_ms},{fade_out_ms})\\fs{title_font_size}}}{title_text}\\N\n"

        # Calculate timeline and add chunked subtitle events
        # Start immediately - dialogue begins right away
        current_time = 0.0

        for audio_info in audio_files:
            duration = get_audio_duration(audio_info["audio_path"])

            character = audio_info["character"]
            text = audio_info["text"]
            audio_path = audio_info["audio_path"]

            # Strip emotion markers for caption display
            # (emotion markers are kept for TTS generation, but removed here)
            text_for_display = strip_emotion_markers(text)

            # Get script words (these are what we want to display)
            script_words = text_for_display.split()

            # Get word-level timestamps from Whisper (for timing only, not for text)
            timestamp_cache = output_dir / f"{audio_path.stem}_timestamps.json"
            timestamp_files.append(timestamp_cache)  # Track for cleanup
            whisper_timings = self.transcriber.get_word_timestamps(
                audio_path, text_for_display, timestamp_cache
            )

            # Align script words with Whisper timestamps
            # This uses script words for captions but Whisper timestamps for timing
            word_timings = self._align_script_words_with_timestamps(
                script_words, whisper_timings, duration
            )

            # Add karaoke-style word highlights
            # Each word appears in character color as it's spoken (no overlapping text)
            karaoke_style = f"{character}_kara"
            for word_timing in word_timings:
                word_start = current_time + word_timing['start']
                word_end = current_time + word_timing['end']

                # Format times for this word
                word_start_time = self._format_ass_time(word_start)
                word_end_time = self._format_ass_time(word_end)

                # Add karaoke word display (character color with black outline)
                ass_content += f"Dialogue: 0,{word_start_time},{word_end_time},{karaoke_style},,0,0,0,,{word_timing['word']}\\N\n"

            current_time += duration
        
        # Write subtitle file
        with open(subtitle_path, 'w', encoding='utf-8-sig') as f:
            f.write(ass_content)

        return subtitle_path, timestamp_files

