"""Video composition using FFmpeg directly - more reliable than MoviePy."""

import subprocess
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from config import (
    get_topic_dirs,
)
from video.transcription import Transcriber
from video.subtitles import SubtitleGenerator
from video.character_timing import CharacterTimingCalculator
from video.ffmpeg_builder import FFmpegCommandBuilder
from video.hls_builder import build_hls_output, create_master_playlist, generate_poster_image
from utils.media_utils import check_ffmpeg, get_audio_duration


class VideoComposerFFmpeg:
    """Composes final video using FFmpeg directly."""

    def __init__(self, topic: str = None):
        self.topic = topic
        self.transcriber = Transcriber()
        self.subtitle_generator = SubtitleGenerator(self.transcriber)
        self.character_timing_calculator = CharacterTimingCalculator(self.transcriber)
        self.ffmpeg_builder = FFmpegCommandBuilder()

    def compose_video(
        self,
        audio_files: List[Dict],
        script: Dict,
        output_name: str = None
    ) -> Path:
        """
        Compose the final video using FFmpeg.

        Args:
            audio_files: List of audio info dicts from TTSGenerator
            script: Script dictionary with topic and lines
            output_name: Optional output filename (without extension)

        Returns:
            Path to the generated master.m3u8 file in hls/{video_id}/ structure
        """
        print("Composing video with FFmpeg...")

        # Check FFmpeg availability
        if not check_ffmpeg():
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg:\n"
                "  Windows: choco install ffmpeg  OR  scoop install ffmpeg\n"
                "  Mac: brew install ffmpeg\n"
                "  Linux: sudo apt install ffmpeg"
            )

        # Setup paths
        topic = self.topic or script["topic"]
        topic_dirs = get_topic_dirs(topic)
        
        if output_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"video_{timestamp}"

        # Create hls/{video_id}/ structure
        hls_base = topic_dirs['video'] / "hls"
        video_id = output_name
        video_dir = hls_base / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        
        # Transcribe all audio files in parallel (before they're needed)
        print("Transcribing audio files for word-level timestamps...")
        self.transcriber.transcribe_all_audio_parallel(audio_files, video_dir)
        
        # Get background video (randomly selected)
        background = self.ffmpeg_builder.get_background_video()
        print(f"Using background: {background.name}")

        # Concatenate audio files
        print("Concatenating audio files...")
        full_audio = self.ffmpeg_builder.concatenate_audio(audio_files, video_dir)

        # Create subtitle file with title sequence
        # Use LLM-generated title from script
        video_title = script["title"]
        print("Creating subtitles...")
        subtitle_file, timestamp_files = self.subtitle_generator.create_subtitle_file(
            audio_files, video_dir, video_title
        )

        # Get total duration needed for the video
        total_duration = get_audio_duration(full_audio)
        print(f"Total duration: {total_duration:.2f} seconds")

        # Calculate character image timings (now dynamic for any characters)
        print("Calculating character image timings...")
        character_image_times, character_image_paths = \
            self.character_timing_calculator.calculate_image_timings(
                audio_files, video_dir
            )

        # Calculate random start time for background
        random_start = self.ffmpeg_builder.calculate_background_start_time(
            background, total_duration
        )
        print(f"Starting background at: {random_start:.2f} seconds")

        # Extract character group name from script cache key
        # Cache key format: {job_description}|{character_group_name}|{template_name}
        character_group_name = None
        if "_cache_key" in script:
            cache_key_parts = script["_cache_key"].split("|")
            if len(cache_key_parts) >= 2:
                character_group_name = cache_key_parts[1]
        
        # Build FFmpeg filter complex (now handles dynamic characters)
        print("Building FFmpeg filter complex...")
        filter_complex = self.ffmpeg_builder.build_filter_complex(
            subtitle_file,
            character_image_times,
            character_image_paths,
            audio_files=audio_files,
            character_group_name=character_group_name
        )

        # Build FFmpeg command for HLS output
        filter_file = video_dir / "filter_complex.txt"
        hls_cmd, rendition_playlist = build_hls_output(
            background,
            full_audio,
            filter_complex,
            filter_file,
            random_start,
            total_duration,
            video_dir,
            title=video_title
        )

        # Run FFmpeg with progress reporting
        from config import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
        print("Rendering HLS video...")
        print(f"  Resolution: {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {VIDEO_FPS}fps")
        print(f"  Duration: {total_duration:.1f}s")
        print(f"  Segment duration: 2.0s")
        print(f"  Estimated render time: {total_duration * 0.3:.1f}s - {total_duration * 0.6:.1f}s")
        print("  (Progress indicators will appear from FFmpeg)")
        
        result = subprocess.run(hls_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"\nFFmpeg error: {result.stderr}")
            # Save filter complex file for debugging if render failed
            print(f"Filter complex saved to: {filter_file}")
            filter_file_debug = filter_file.parent / f"filter_complex_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filter_file.rename(filter_file_debug)
            raise RuntimeError(f"FFmpeg failed with return code {result.returncode}")

        # Create master playlist
        print("Creating master playlist...")
        master_playlist = create_master_playlist(
            video_dir,
            rendition_playlist
        )
        print(f"Master playlist: {master_playlist}")

        # Generate poster image from first segment
        print("Generating poster image...")
        first_segment = video_dir / "720p" / "seg_000.ts"
        poster_path = video_dir / "poster.jpg"
        if first_segment.exists():
            generate_poster_image(first_segment, poster_path)
            print(f"Poster image: {poster_path}")
        else:
            print(f"Warning: First segment not found, skipping poster generation")

        # Clean up temporary files
        print("Cleaning up temporary files...")
        full_audio.unlink()
        subtitle_file.unlink()
        concat_file = video_dir / "concat_list.txt"
        if concat_file.exists():
            concat_file.unlink()
        filter_file.unlink()

        # Clean up timestamp cache files
        for timestamp_file in timestamp_files:
            if timestamp_file.exists():
                timestamp_file.unlink()

        print(f"[SUCCESS] HLS video generated successfully:")
        print(f"  Master playlist: {master_playlist}")
        print(f"  Rendition playlist: {rendition_playlist}")
        return master_playlist


if __name__ == "__main__":
    # Test video composer with cached data
    import sys
    import json
    
    # Check if topic provided as argument
    if len(sys.argv) > 1:
        topic = sys.argv[1]
    else:
        # Try to find a topic in cache
        from config import CACHE_DIR
        topics = [d for d in CACHE_DIR.iterdir() if d.is_dir() and not d.name in ['scripts', 'audio']]
        if not topics:
            print("No topics found in cache.")
            sys.exit(1)
        topic = topics[0].name
        print(f"Using topic: {topic}")
    
    # Get topic directories
    topic_dirs = get_topic_dirs(topic)
    
    # Load script
    script_path = topic_dirs['scripts'] / 'script.json'
    if not script_path.exists():
        print(f"Error: No script found at {script_path}")
        sys.exit(1)
    
    with open(script_path, 'r', encoding='utf-8') as f:
        script = json.load(f)
    
    print(f"Loaded script with {len(script['lines'])} lines")
    
    # Collect audio files (handle both old and new format)
    audio_files = []
    for line_index, line in enumerate(script['lines']):
        character = line['character']
        
        # New format: text and images array
        if "text" in line and "images" in line:
            audio_path = topic_dirs['audio'] / f"{character}_{line_index}.mp3"
            if not audio_path.exists():
                print(f"Error: Audio file not found: {audio_path}")
                sys.exit(1)
            audio_files.append({
                'character': character,
                'text': line['text'],
                'images': line['images'],
                'audio_path': audio_path,
                'line_index': line_index
            })
        elif "segments" in line:
            # Old format: segments (backward compatibility)
            for segment_index, segment in enumerate(line['segments']):
                audio_path = topic_dirs['audio'] / f"{character}_{line_index}_{segment_index}.mp3"
                if not audio_path.exists():
                    print(f"Error: Audio file not found: {audio_path}")
                    sys.exit(1)
                audio_files.append({
                    'character': character,
                    'text': segment['text'],
                    'emotion': segment.get('emotion', 'calm'),
                    'image': segment.get('image', 'default'),
                    'audio_path': audio_path,
                    'line_index': line_index,
                    'segment_index': segment_index
                })
        else:
            # Old format: single audio per line
            audio_path = topic_dirs['audio'] / f"{character}_{line_index}.mp3"
            if not audio_path.exists():
                # Try old segment format as fallback
                audio_path = topic_dirs['audio'] / f"{character}_{line_index}_0.mp3"
                if not audio_path.exists():
                    print(f"Error: Audio file not found: {audio_path}")
                    sys.exit(1)
            audio_files.append({
                'character': character,
                'text': line.get('text', ''),
                'images': [line.get('image', 'default')],
                'audio_path': audio_path,
                'line_index': line_index
            })
    
    print(f"Found {len(audio_files)} audio files")
    
    # Compose video
    composer = VideoComposerFFmpeg(topic=topic)
    video_path = composer.compose_video(audio_files, script)
    
    print(f"\n{'='*60}")
    print(f"SUCCESS! Video generated:")
    print(f"  {video_path}")
    print(f"{'='*60}")
