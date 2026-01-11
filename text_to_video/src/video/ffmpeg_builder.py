"""FFmpeg command building for video composition."""

import random
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    CHARACTER_SIZE,
    CHARACTER_BOTTOM_MARGIN,
    CHARACTER_EDGE_MARGIN,
    CHARACTER_GROUP_COLORS,
    BACKGROUNDS_DIR,
    PROJECT_ROOT,
)
from utils.media_utils import get_video_duration


class FFmpegCommandBuilder:
    """Builds FFmpeg commands for video composition."""

    def __init__(self):
        pass

    def get_background_video(self) -> Path:
        """Find and randomly select a background video file."""
        video_files = list(BACKGROUNDS_DIR.glob("*.mp4")) + \
                     list(BACKGROUNDS_DIR.glob("*.mov")) + \
                     list(BACKGROUNDS_DIR.glob("*.avi"))

        if not video_files:
            raise FileNotFoundError(
                f"No background video found in {BACKGROUNDS_DIR}"
            )

        # Randomly select a background video
        return random.choice(video_files)

    def concatenate_audio(self, audio_files: List[Dict], output_dir: Path) -> Path:
        """Concatenate all audio files into one with volume normalization."""
        concat_file = output_dir / "concat_list.txt"
        audio_output = output_dir / "full_audio.m4a"

        # Validate input
        if not audio_files:
            raise ValueError("No audio files provided for concatenation")

        print(f"Concatenating {len(audio_files)} audio files...")

        # Verify all audio files exist before creating concat list
        missing_files = []
        for audio_info in audio_files:
            audio_path = Path(audio_info["audio_path"])
            if not audio_path.exists():
                missing_files.append(str(audio_path))
        
        if missing_files:
            raise FileNotFoundError(f"Audio files not found:\n" + "\n".join(missing_files))

        # Create concat file for FFmpeg
        # FFmpeg concat demuxer format: file 'path' (with single quotes)
        # On Windows, paths need special handling - use forward slashes or escape backslashes
        try:
            concat_lines = []
            for audio_info in audio_files:
                audio_path = Path(audio_info["audio_path"])
                # Use absolute path
                abs_path = audio_path.resolve()
                # Convert to string and normalize path separators
                # FFmpeg on Windows works better with forward slashes in concat files
                audio_path_str = str(abs_path).replace('\\', '/')
                # Escape single quotes if present (though unlikely in Windows paths)
                if "'" in audio_path_str:
                    audio_path_str = audio_path_str.replace("'", "'\\''")
                # Format: file 'path'
                concat_lines.append(f"file '{audio_path_str}'")
            
            # Write all lines at once with Unix line endings
            with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(concat_lines) + '\n')
            
            print(f"Wrote {len(concat_lines)} entries to concat file")
            
            # Verify file was written correctly
            with open(concat_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    # Debug: print what we tried to write
                    print(f"ERROR: Concat file is empty after writing!")
                    print(f"audio_files count: {len(audio_files)}")
                    print(f"First few audio_files entries:")
                    for i, af in enumerate(audio_files[:3]):
                        print(f"  [{i}] {af}")
                    raise ValueError(f"Concat file is empty after writing. audio_files count: {len(audio_files)}")
                lines = content.strip().split('\n')
                print(f"Concat file created with {len(lines)} entries")
                # Debug: show first few lines
                if lines:
                    print(f"First concat entry: {lines[0][:100]}")
        except Exception as e:
            print(f"Exception during concat file creation: {e}")
            print(f"audio_files type: {type(audio_files)}, length: {len(audio_files) if audio_files else 0}")
            raise RuntimeError(f"Failed to create concat file: {e}")

        # Concatenate audio files and re-encode to AAC in M4A container
        # M4A/AAC avoids MP3 frame boundary issues and is compatible with MP4 muxing
        # Note: Removed loudnorm filter for speed - Fish Audio TTS already has consistent volume
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(concat_file),
            '-c:a', 'aac',      # AAC codec
            '-b:a', '192k',     # Bitrate
            '-y',               # Overwrite output
            str(audio_output)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as e:
            # Print the actual error message from ffmpeg
            error_msg = e.stderr if e.stderr else "No error message available"
            print(f"FFmpeg error output: {error_msg}")
            print(f"FFmpeg command: {' '.join(cmd)}")
            print(f"Concat file contents:")
            with open(concat_file, 'r', encoding='utf-8') as f:
                print(f.read())
            raise
        
        return audio_output

    def build_enable_expr_for_image(self, image_times: List[Tuple[float, float]]) -> str:
        """
        Build enable expression for a specific image variant.
        
        Args:
            image_times: List of (start, end) time tuples
            
        Returns:
            FFmpeg enable expression string
        """
        if not image_times:
            return "0"  # Never show

        conditions = []
        for start, end in image_times:
            conditions.append(f"between(t,{start},{end})")

        return "+".join(conditions)

    def build_filter_complex(
        self,
        subtitle_path: Path,
        character_image_times: Dict[str, Dict[str, List[Tuple[float, float]]]],
        character_image_paths: Dict[str, Dict[str, Path]],
        audio_files: List[Dict] = None,
        character_group_name: str = None
    ) -> str:
        """
        Build FFmpeg filter_complex string for video composition with DYNAMIC characters.
        
        Args:
            subtitle_path: Path to ASS subtitle file
            character_image_times: Dict[character_name][image_name] -> list of (start, end) tuples
            character_image_paths: Dict[character_name][image_name] -> Path
            audio_files: Optional list of audio file dicts to determine character speaking order
            
        Returns:
            Filter complex string for FFmpeg
        """
        # Calculate positions: Characters positioned based on speaking order
        char_width, char_height = CHARACTER_SIZE
        char_y = VIDEO_HEIGHT - char_height - CHARACTER_BOTTOM_MARGIN
        
        # Get list of all characters
        characters = list(character_image_times.keys())
        num_characters = len(characters)
        
        # Determine character order based on first appearance in audio_files
        character_order = []
        if audio_files:
            seen = set()
            for audio_info in audio_files:
                char = audio_info.get("character", "").lower()
                if char and char not in seen:
                    character_order.append(char)
                    seen.add(char)
        
        # If we couldn't determine order from audio_files, use sorted order as fallback
        if not character_order or len(character_order) != num_characters:
            character_order = sorted(characters)
        
        # Calculate X positions based on speaking order
        # CRITICAL: Position characters so their CENTERS align at fixed positions
        # This ensures when characters switch, their centers stay in the same place
        # First speaker: bottom left, Second: bottom right, Third: bottom center
        
        # Define center X positions for each slot (centers stay fixed)
        left_center_x = CHARACTER_EDGE_MARGIN + char_width / 2
        right_center_x = VIDEO_WIDTH - CHARACTER_EDGE_MARGIN - char_width / 2
        center_center_x = VIDEO_WIDTH / 2
        
        # Position characters so their centers align with slot centers
        char_positions = {}
        if num_characters == 1:
            # Single character: bottom left (center aligned)
            char_positions[character_order[0]] = int(left_center_x - char_width / 2)
        elif num_characters == 2:
            # Two characters: first on left, second on right (centers aligned)
            char_positions[character_order[0]] = int(left_center_x - char_width / 2)  # Left center
            char_positions[character_order[1]] = int(right_center_x - char_width / 2)  # Right center
        elif num_characters == 3:
            # Three characters: first on left, second on right, third in center (centers aligned)
            char_positions[character_order[0]] = int(left_center_x - char_width / 2)  # Left center
            char_positions[character_order[1]] = int(right_center_x - char_width / 2)  # Right center
            char_positions[character_order[2]] = int(center_center_x - char_width / 2)  # Center center
        else:
            # More than 3 characters: distribute evenly with aligned centers
            slot_centers = []
            spacing = (VIDEO_WIDTH - 2 * CHARACTER_EDGE_MARGIN - char_width) / (num_characters - 1)
            for i in range(num_characters):
                slot_centers.append(CHARACTER_EDGE_MARGIN + char_width / 2 + i * spacing)
            for i, char in enumerate(character_order):
                char_positions[char] = int(slot_centers[i] - char_width / 2)
        
        # Start building filter complex
        filter_parts = [
            f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"fps={VIDEO_FPS}[bg];"
        ]

        # Convert subtitle path for FFmpeg (escape special characters)
        subtitle_path_unix = str(subtitle_path).replace('\\', '/').replace(':', '\\\\:')

        # Get color tint for this character group
        group_color = CHARACTER_GROUP_COLORS.get(character_group_name, None)
        
        # Add movie filters and overlays for each character's images
        current_pad = "bg"
        pad_counter = 1
        
        for character in sorted(characters):
            char_x = char_positions[character]
            char_images = character_image_times[character]
            
            for image in sorted(char_images.keys()):
                image_path = str(character_image_paths[character][image]).replace('\\', '/').replace(':', '\\\\:')
                image_enable = self.build_enable_expr_for_image(char_images[image])
                pad_name = f"v{pad_counter}"
                
                # Scale all characters to EXACT same size to ensure centers align
                # force_original_aspect_ratio=decrease ensures they fit within bounds
                # Then pad to exact size if needed to maintain consistent positioning
                scale_filter = f"movie={image_path},scale=w={char_width}:h={char_height}:force_original_aspect_ratio=decrease,"
                scale_filter += f"pad={char_width}:{char_height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,format=rgba"
                
                # Apply color tint if group color is specified
                if group_color:
                    # Convert hex color to RGB values for colorbalance filter
                    # Format: #RRGGBB -> extract RGB
                    hex_color = group_color.lstrip('#')
                    r = int(hex_color[0:2], 16) / 255.0
                    g = int(hex_color[2:4], 16) / 255.0
                    b = int(hex_color[4:6], 16) / 255.0
                    # Apply subtle tint (0.1 = 10% tint, 0.2 = 20% tint)
                    tint_strength = 0.15  # 15% tint for subtle but visible distinction
                    scale_filter += f",colorbalance=rs={tint_strength * r}:gs={tint_strength * g}:bs={tint_strength * b}"
                
                scale_filter += f"[{character}_{image}];"
                filter_parts.append(scale_filter)
                
                filter_parts.append(
                    f"[{current_pad}][{character}_{image}]overlay={char_x}:{char_y}:enable='{image_enable}'[{pad_name}];"
                )
                current_pad = pad_name
                pad_counter += 1

        # Apply subtitles last
        # Note: libass will use system fonts - install Nunito-Black.ttf for best results
        filter_parts.append(f"[{current_pad}]subtitles={subtitle_path_unix}[v]")

        return "".join(filter_parts)

    def build_ffmpeg_command(
        self,
        background_path: Path,
        audio_path: Path,
        output_path: Path,
        filter_complex: str,
        filter_file: Path,
        random_start: float,
        total_duration: float,
        title: str = "Educational Content"
    ) -> List[str]:
        """
        Build complete FFmpeg command for video composition.
        
        Args:
            background_path: Path to background video
            audio_path: Path to concatenated audio file
            output_path: Path for output video
            filter_complex: Filter complex string
            filter_file: Path to filter complex file
            random_start: Random start time in background video
            total_duration: Total duration of the video
            title: Video title for metadata
            
        Returns:
            List of command arguments for subprocess
        """
        # Write filter complex to file to avoid command-line length limits
        filter_file.write_text(filter_complex, encoding='utf-8')
        
        return [
            'ffmpeg',
            '-ss', str(random_start),  # Start from random point in background
            '-stream_loop', '-1',  # Loop background video if needed
            '-i', str(background_path),
            '-i', str(audio_path),
            '-filter_complex_script', str(filter_file),  # Read filter from file
            '-map', '[v]',        # Use filtered video
            '-map', '1:a',        # Use audio from second input (character voices)
            '-shortest',          # End when shortest stream ends
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '21',         # Slightly better quality for shorts (21 vs 23)
            '-pix_fmt', 'yuv420p',  # Ensure compatibility with all players
            '-profile:v', 'high', # H.264 High Profile for better compression
            '-level', '4.2',      # Supports up to 4K video
            '-movflags', '+faststart',  # Enable streaming/fast web playback
            '-c:a', 'copy',       # Audio already in AAC format from concatenation
            # Add metadata for better organization
            '-metadata', f'title={title}',
            '-metadata', 'comment=Generated by PeterCS',
            '-metadata', 'description=Educational content generated using AI',
            '-y',  # Overwrite output
            str(output_path)
        ]

    def calculate_background_start_time(
        self,
        background_path: Path,
        total_duration: float
    ) -> float:
        """
        Calculate random start time for background video.
        
        Args:
            background_path: Path to background video
            total_duration: Total duration needed
            
        Returns:
            Random start time in seconds
        """
        background_duration = get_video_duration(background_path)
        
        # Calculate random start point ensuring enough duration remains
        # We need: start_time + total_duration <= background_duration
        # So: start_time <= background_duration - total_duration
        max_start_time = max(0, background_duration - total_duration)
        
        if max_start_time <= 0:
            # Background is shorter than needed, start from beginning (will loop)
            return 0.0
        else:
            # Randomly select a start point
            return random.uniform(0, max_start_time)

    def build_hls_output(
        self,
        background_path: Path,
        audio_path: Path,
        filter_complex: str,
        filter_file: Path,
        random_start: float,
        total_duration: float,
        output_dir: Path,
        title: str = "Educational Content"
    ) -> Tuple[Path, Path]:
        """
        Build FFmpeg command for HLS output with proper segmenting.
        
        Args:
            background_path: Path to background video
            audio_path: Path to concatenated audio file
            filter_complex: Filter complex string
            filter_file: Path to filter complex file
            random_start: Random start time in background video
            total_duration: Total duration of the video
            output_dir: Directory to output HLS files
            title: Video title for metadata
            
        Returns:
            Tuple of (master_playlist_path, rendition_playlist_path)
        """
        from config import VIDEO_FPS
        
        # Create 720p directory for segments
        hls_dir = output_dir / "720p"
        hls_dir.mkdir(parents=True, exist_ok=True)
        
        # Write filter complex to file
        filter_file.write_text(filter_complex, encoding='utf-8')
        
        # Calculate GOP size: 2 seconds * fps = 60 frames for 30fps
        gop_size = int(2.0 * VIDEO_FPS)  # 60 frames for 30fps
        
        # HLS output parameters
        segment_pattern = str(hls_dir / "seg_%03d.ts")
        playlist_path = hls_dir / "index.m3u8"
        
        # Build FFmpeg command for HLS
        cmd = [
            'ffmpeg',
            '-ss', str(random_start),
            '-stream_loop', '-1',
            '-i', str(background_path),
            '-i', str(audio_path),
            '-filter_complex_script', str(filter_file),
            '-map', '[v]',
            '-map', '1:a',
            '-shortest',
            # Video encoding: H.264 High profile, level 3.1-4.0
            '-c:v', 'libx264',
            '-profile:v', 'high',
            '-level', '4.0',  # Level 4.0 (can be 3.1-4.0 range)
            '-preset', 'medium',
            '-crf', '23',  # CRF 23 as specified
            '-maxrate', '3M',  # Optional bitrate cap: 3 Mbps
            '-bufsize', '6M',  # Buffer size: 6 Mbps
            # Keyframe settings: GOP matches segment boundaries
            '-g', str(gop_size),  # GOP size = 60 frames (2 seconds at 30fps)
            '-keyint_min', str(gop_size),  # Minimum keyframe interval
            '-sc_threshold', '0',  # Disable scene cut detection (scenecut off)
            '-pix_fmt', 'yuv420p',
            # Audio encoding: AAC-LC, 44.1 kHz, stereo, 128 kbps
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',  # 44.1 kHz (can also use 48000)
            '-ac', '2',  # Stereo
            '-profile:a', 'aac_low',  # AAC-LC profile
            # HLS output settings
            '-f', 'hls',
            '-hls_time', '2.0',  # 2-second segments
            '-hls_playlist_type', 'vod',  # VOD playlist type
            '-hls_segment_filename', segment_pattern,
            '-hls_list_size', '0',  # Keep all segments in playlist
            '-hls_flags', 'independent_segments',  # Each segment can be decoded independently
            # Metadata
            '-metadata', f'title={title}',
            '-metadata', 'comment=Generated by PeterCS',
            '-y',
            str(playlist_path)
        ]
        
        return cmd, playlist_path

    def create_master_playlist(
        self,
        output_dir: Path,
        rendition_playlist: Path,
        video_width: int = 1080,
        video_height: int = 1920
    ) -> Path:
        """
        Create master.m3u8 playlist pointing to rendition.
        
        Args:
            output_dir: Directory to output master playlist
            rendition_playlist: Path to the rendition playlist (720p/index.m3u8)
            video_width: Video width in pixels
            video_height: Video height in pixels
            
        Returns:
            Path to master playlist
        """
        master_playlist = output_dir / "master.m3u8"
        
        # Calculate bandwidth estimate (rough: bitrate * 1.2 for overhead)
        # Using maxrate 3M + audio 128k = ~3.1M, estimate ~3.7M total with overhead
        bandwidth = 3700000  # ~3.7 Mbps
        
        # H.264 codec string: avc1.640028 (High profile, level 4.0)
        # AAC codec string: mp4a.40.2 (AAC-LC)
        codecs = 'avc1.640028,mp4a.40.2'
        
        # Relative path from master to rendition
        relative_path = rendition_playlist.relative_to(output_dir)
        relative_path_str = str(relative_path).replace('\\', '/')
        
        master_content = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={video_width}x{video_height},CODECS="{codecs}"
{relative_path_str}
"""
        
        master_playlist.write_text(master_content, encoding='utf-8')
        return master_playlist
