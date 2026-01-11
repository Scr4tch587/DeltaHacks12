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
        """
        if not whisper_timings:
            # No Whisper timings, use estimated timing
            time_per_word = duration / max(len(script_words), 1)
            return [
                {'word': w, 'start': i * time_per_word, 'end': (i + 1) * time_per_word}
                for i, w in enumerate(script_words)
            ]
        
        def normalize_word(w):
            return w.lower().strip('.,!?;:')
        
        whisper_normalized = [normalize_word(w['word']) for w in whisper_timings]
        
        aligned = []
        whisper_idx = 0
        
        for script_idx, script_word in enumerate(script_words):
            script_norm = normalize_word(script_word)
            
            found_match = False
            search_window = min(5, len(whisper_timings) - whisper_idx)
            
            for i in range(whisper_idx, whisper_idx + search_window):
                if i < len(whisper_normalized) and whisper_normalized[i] == script_norm:
                    aligned.append({
                        'word': script_word,
                        'start': whisper_timings[i]['start'],
                        'end': whisper_timings[i]['end']
                    })
                    whisper_idx = i + 1
                    found_match = True
                    break
            
            if not found_match:
                if whisper_idx < len(whisper_timings):
                    aligned.append({
                        'word': script_word,
                        'start': whisper_timings[whisper_idx]['start'],
                        'end': whisper_timings[whisper_idx]['end']
                    })
                    whisper_idx += 1
                else:
                    if aligned:
                        last_end = aligned[-1]['end']
                        remaining_words = len(script_words) - script_idx
                        remaining_time = max(0, duration - last_end)
                        time_per_word = remaining_time / max(remaining_words, 1)
                        
                        aligned.append({
                            'word': script_word,
                            'start': last_end,
                            'end': last_end + time_per_word
                        })
                    else:
                        time_per_word = duration / len(script_words)
                        aligned.append({
                            'word': script_word,
                            'start': script_idx * time_per_word,
                            'end': (script_idx + 1) * time_per_word
                        })
        
        # Clamp timestamps to duration
        MIN_WORD_DISPLAY_TIME = 0.15
        
        filtered_aligned = []
        for word_timing in aligned:
            if word_timing['start'] < duration:
                if word_timing['end'] > duration:
                    word_timing['end'] = duration

                min_end = word_timing['start'] + MIN_WORD_DISPLAY_TIME
                if word_timing['end'] < min_end:
                    word_timing['end'] = min(min_end, duration)

                filtered_aligned.append(word_timing)

        if filtered_aligned and filtered_aligned[-1]['end'] < duration:
            filtered_aligned[-1]['end'] = duration

        return filtered_aligned

    def _chunk_words_by_width(self, word_timings: List[Dict]) -> List[List[Dict]]:
        """
        Chunk words into groups that fit within screen width.
        
        Uses pixel-based estimation to ensure text fits on one line.
        
        Args:
            word_timings: List of word timing dicts with 'word', 'start', 'end'

        Returns:
            List of word chunks, where each chunk is a list of word timing dicts
        """
        if not word_timings:
            return []

        # Estimate character width for Nunito-Black at CAPTION_FONT_SIZE
        # Bold fonts are wider - approximately 0.65x font size per character
        char_width = CAPTION_FONT_SIZE * 0.65
        space_width = CAPTION_FONT_SIZE * 0.3
        
        # Max width with padding (leave 10% margin on each side)
        max_width = VIDEO_WIDTH * 0.80

        chunks = []
        current_chunk = []
        current_width = 0

        for word_timing in word_timings:
            word = word_timing['word']
            word_width = len(word) * char_width + space_width

            # Start new chunk if this word would exceed max width
            if current_chunk and (current_width + word_width > max_width):
                chunks.append(current_chunk)
                current_chunk = [word_timing]
                current_width = len(word) * char_width
            else:
                current_chunk.append(word_timing)
                current_width += word_width

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

    def _hex_to_ass_color(self, hex_color: str) -> str:
        """Convert hex color (#RRGGBB) to ASS format (&H00BBGGRR)."""
        hex_color = hex_color.strip().lower()
        
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
        
        if hex_color in color_map:
            return color_map[hex_color]
        
        if hex_color.startswith("#") and len(hex_color) == 7:
            try:
                r = int(hex_color[1:3], 16)
                g = int(hex_color[3:5], 16)
                b = int(hex_color[5:7], 16)
                return f"&H00{b:02X}{g:02X}{r:02X}"
            except ValueError:
                pass
        
        return "&H00FFFFFF"

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
        timestamp_files = []

        # Fixed position for captions (center-bottom)
        caption_x = VIDEO_WIDTH // 2
        caption_y = CAPTION_VERTICAL_POS

        # Calculate margin from bottom for title
        caption_margin_bottom = VIDEO_HEIGHT - CAPTION_VERTICAL_POS

        bold_value = -1 if CAPTION_FONT_WEIGHT >= 700 else 0
        title_bold = -1 if TITLE_FONT_WEIGHT >= 700 else 0

        # Get unique characters
        characters_in_script = list(set(audio_info["character"] for audio_info in audio_files))
        
        from config import CHARACTERS

        # ASS header - WrapStyle 0 for title (allows wrapping), captions use \q2 override
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
        
        # Add styles for each character - these use fixed positioning via override tags
        for character in characters_in_script:
            if character in CHARACTERS:
                char_color_hex = CHARACTERS[character].get("caption_color", "white")
            else:
                char_color_hex = "white"
            
            ass_color = self._hex_to_ass_color(char_color_hex)
            
            # Alignment 2 = bottom-center
            ass_content += f"Style: {character},Nunito-Black,{CAPTION_FONT_SIZE},{ass_color},&H00FFFFFF,&H00000000,&HFF000000,{bold_value},0,0,0,100,100,0,0,1,{CAPTION_STROKE_WIDTH},0,2,40,40,{caption_margin_bottom},1\n"
        
        # Title style - Alignment 8 = top-center, allows word wrapping
        title_margin_horizontal = 40
        ass_content += f"Style: title,Nunito-Black,{TITLE_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&HFF000000,{title_bold},0,0,0,100,100,0,0,1,{TITLE_STROKE_WIDTH},0,8,{title_margin_horizontal},{title_margin_horizontal},100,1\n"
        
        ass_content += """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Add title (allows multi-line wrapping)
        title_text = title.upper()
        estimated_chars = len(title_text)
        if estimated_chars > 0:
            max_width = VIDEO_WIDTH * 0.8
            calculated_font_size = int(max_width / (estimated_chars * 0.55))
            title_font_size = max(80, min(calculated_font_size, TITLE_FONT_SIZE))
        else:
            title_font_size = TITLE_FONT_SIZE
        
        title_start = self._format_ass_time(0)
        title_end = self._format_ass_time(TITLE_DURATION)
        fade_in_ms = 0
        fade_out_ms = int(TITLE_FADE_DURATION * 1000)
        
        # Title uses style wrapping (no \q2), can be multi-line
        ass_content += f"Dialogue: 0,{title_start},{title_end},title,,0,0,0,,{{\\fad({fade_in_ms},{fade_out_ms})\\fs{title_font_size}}}{title_text}\n"

        # Process audio files and create subtitle events
        current_time = 0.0

        for audio_info in audio_files:
            duration = get_audio_duration(audio_info["audio_path"])
            character = audio_info["character"]
            text = audio_info["text"]
            audio_path = audio_info["audio_path"]

            # Strip emotion markers
            text_for_display = strip_emotion_markers(text)
            script_words = text_for_display.split()

            # Get word timestamps
            timestamp_cache = output_dir / f"{audio_path.stem}_timestamps.json"
            timestamp_files.append(timestamp_cache)
            whisper_timings = self.transcriber.get_word_timestamps(
                audio_path, text_for_display, timestamp_cache
            )

            # Align words with timestamps
            word_timings = self._align_script_words_with_timestamps(
                script_words, whisper_timings, duration
            )

            # Chunk words to fit within screen width
            chunks = self._chunk_words_by_width(word_timings)

            # Add each chunk as a single subtitle event with fixed position
            # Ensure no overlap: each chunk ends when the next one starts
            for i, chunk in enumerate(chunks):
                if not chunk:
                    continue
                
                chunk_start = current_time + chunk[0]['start']
                
                # End time: start of next chunk, or end of last word if this is the last chunk
                if i + 1 < len(chunks) and chunks[i + 1]:
                    # End exactly when next chunk starts (no overlap)
                    chunk_end = current_time + chunks[i + 1][0]['start']
                else:
                    # Last chunk: end when last word ends
                    chunk_end = current_time + chunk[-1]['end']
                
                # Build chunk text (all words in chunk)
                chunk_text = " ".join(w['word'] for w in chunk)
                
                start_time = self._format_ass_time(chunk_start)
                end_time = self._format_ass_time(chunk_end)
                
                # \an2 = bottom-center alignment
                # \pos(x,y) = fixed position
                # \q2 = no word wrap (force single line)
                pos_tag = f"{{\\an2\\pos({caption_x},{caption_y})\\q2}}"
                
                ass_content += f"Dialogue: 0,{start_time},{end_time},{character},,0,0,0,,{pos_tag}{chunk_text}\n"

            current_time += duration
        
        # Write subtitle file
        with open(subtitle_path, 'w', encoding='utf-8-sig') as f:
            f.write(ass_content)

        return subtitle_path, timestamp_files