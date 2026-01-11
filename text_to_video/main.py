"""Main orchestrator for Family Guy content generator."""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from script_generator import ScriptGenerator
from tts_generator import TTSGenerator
from video_composer_ffmpeg import VideoComposerFFmpeg
from config import get_topic_dirs


def load_job_description(file_path: str = None) -> str:
    """
    Load job description from file.
    
    Args:
        file_path: Path to job description file. If None, uses default location.
        
    Returns:
        Job description text as string
    """
    if file_path is None:
        # Default to prompts/job_description.txt
        prompts_dir = Path(__file__).parent / "src" / "prompts"
        file_path = prompts_dir / "job_description.txt"
    else:
        file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Job description file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def generate_content(job_description: str, step: str = "all", force_regenerate: bool = False,
                    output_name: str = None):
    """
    Generate short-form content for the given job description.

    Args:
        job_description: The job description text to generate content about
        step: Which step to execute ('script', 'tts', 'video', 'all')
        force_regenerate: If True, bypass cache and regenerate everything
        output_name: Optional name for the output video
    """
    print(f"\n{'='*60}")
    print(f"Job Description Content Generator")
    print(f"{'='*60}")
    print(f"Job Description: {job_description[:100]}...")
    print(f"Step: {step}")
    print(f"Force regenerate: {force_regenerate}")
    print(f"{'='*60}\n")

    # Step 1: Generate script
    if step in ["script", "all"]:
        print("\n--- STEP 1: GENERATING SCRIPT ---")
        generator = ScriptGenerator()
        script = generator.generate_script(job_description, force_regenerate=force_regenerate)
        print(f"\nScript generated with {len(script['lines'])} lines")

        if step == "script":
            print("\nScript preview:")
            print(f"Title: {script['title']}")
            print(f"Lines: {len(script['lines'])}")
            for i, line in enumerate(script['lines']):
                print(f"{i+1}. [{line['character'].upper()}]: {line['text']}")
            return script

    else:
        # Load existing script from cache
        # Note: Script cache key includes character_group|template, so we need to search for it
        generator = ScriptGenerator()
        # Try to find the cached script - it might be in a directory with character_group|template suffix
        # For now, try loading with just job_description (will work if script was cached before the change)
        script = generator._load_from_cache(job_description)
        if not script:
            # Try to find any cached script for this job description
            # Search cache directories that start with the job description slug
            from config import CACHE_DIR
            import glob
            topic_dirs = get_topic_dirs(job_description)
            # Look for script.json in any subdirectory that matches the job description pattern
            cache_root = CACHE_DIR
            script_files = list(cache_root.glob(f"*/scripts/script.json"))
            if script_files:
                # Try loading the first one found (or we could be smarter and match by job description hash)
                from utils.cache import load_script_cache
                script = load_script_cache(script_files[0])
                if script:
                    print(f"Found cached script in: {script_files[0].parent.parent.name}")
                else:
                    print(f"Error: No cached script found for job description")
                    print("Run with --step script first, or use --step all")
                    sys.exit(1)
            else:
                print(f"Error: No cached script found for job description")
                print("Run with --step script first, or use --step all")
                sys.exit(1)

    # Step 2: Generate TTS
    if step in ["tts", "all"]:
        print("\n--- STEP 2: GENERATING TEXT-TO-SPEECH ---")
        # Use the same cache key as the script to keep them in the same directory
        # Extract cache key from script if available, otherwise use job_description
        script_cache_key = script.get("_cache_key", job_description) if isinstance(script, dict) else job_description
        tts = TTSGenerator(topic=script_cache_key)
        audio_files = tts.generate_script_audio(script, force_regenerate=force_regenerate)
        print(f"\nGenerated {len(audio_files)} audio files")

        if step == "tts":
            print("\nAudio files:")
            for audio_info in audio_files:
                print(f"  - {audio_info['audio_path']}")
            return audio_files

    else:
        # Load existing audio files
        # Use the cache key from the script to find audio files in the same cache directory
        cache_key = script.get("_cache_key", job_description) if isinstance(script, dict) else job_description
        topic_dirs = get_topic_dirs(cache_key)
        audio_files = []
        
        # Handle both old format (backward compatibility) and new segment format
        for line_index, line in enumerate(script['lines']):
            character = line['character']
            
            if "segments" in line:
                # New format: segments
                for segment_index, segment in enumerate(line['segments']):
                    audio_path = topic_dirs['audio'] / f"{character}_{line_index}_{segment_index}.mp3"
                    if not audio_path.exists():
                        print(f"Error: No cached audio found for {character} line {line_index} segment {segment_index}")
                        print(f"Expected at: {audio_path}")
                        print("Run with --step tts first, or use --step all")
                        sys.exit(1)
                    audio_files.append({
                        "character": character,
                        "text": segment['text'],
                        "emotion": segment.get('emotion', 'calm'),
                        "image": segment.get('image', 'default'),
                        "audio_path": audio_path,
                        "line_index": line_index,
                        "segment_index": segment_index
                    })
            else:
                # Old format: single audio file per line
                audio_path = topic_dirs['audio'] / f"{character}_{line_index}.mp3"
                if not audio_path.exists():
                    # Try new format as fallback
                    audio_path = topic_dirs['audio'] / f"{character}_{line_index}_0.mp3"
                    if not audio_path.exists():
                        print(f"Error: No cached audio found for line {line_index}")
                        print(f"Expected at: {audio_path}")
                        print("Run with --step tts first, or use --step all")
                        sys.exit(1)
                audio_files.append({
                    "character": character,
                    "text": line.get('text', ''),
                    "emotion": line.get('emotion', 'calm'),
                    "image": line.get('image', 'default'),
                    "audio_path": audio_path,
                    "line_index": line_index,
                    "segment_index": 0
                })
        
        print(f"Loaded {len(audio_files)} audio files from cache")

    # Step 3: Compose video
    if step in ["video", "all"]:
        print("\n--- STEP 3: COMPOSING VIDEO ---")
        # Use the same cache key as the script/audio to ensure video files are in the correct directory
        cache_key = script.get("_cache_key", job_description) if isinstance(script, dict) else job_description
        composer = VideoComposerFFmpeg(topic=cache_key)
        video_path = composer.compose_video(audio_files, script, output_name=output_name)

        print(f"\n{'='*60}")
        print(f"SUCCESS! Video generated:")
        print(f"  {video_path}")
        print(f"{'='*60}\n")

        return video_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate short-form content from job descriptions"
    )
    parser.add_argument(
        "--job-description-file",
        type=str,
        default=None,
        help="Path to job description file (default: src/prompts/job_description.txt)"
    )
    parser.add_argument(
        "--step",
        type=str,
        choices=["script", "tts", "video", "all"],
        default="all",
        help="Which step to execute (default: all)"
    )
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="Bypass cache and regenerate everything"
    )
    parser.add_argument(
        "--output-name",
        type=str,
        default=None,
        help="Optional name for the output video (without extension)"
    )

    args = parser.parse_args()

    try:
        # Load job description from file
        job_description = load_job_description(args.job_description_file)
        
        generate_content(
            job_description=job_description,
            step=args.step,
            force_regenerate=args.force_regenerate,
            output_name=args.output_name
        )
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def generate_video_from_text(job_description: str, output_path: str, output_name: str = "output", output_format: str = "hls"):
    """
    Simple function to generate video from job description text and save to output path.
    
    Args:
        job_description: The job description text (string, not file path)
        output_path: Path where all output files will be saved (scripts, audio, video)
        output_name: Name for the output video file (default: "output")
        output_format: Output format - "hls" for HLS streaming or "mp4" for MP4 file (default: "hls")
    
    Returns:
        Path to the generated video file (HLS master.m3u8 or MP4 file path)
    
    Example:
        # Generate HLS
        video_path = generate_video_from_text(
            job_description="Senior Python Developer...",
            output_path="/tmp/job_videos",
            output_format="hls"
        )
        
        # Generate MP4
        video_path = generate_video_from_text(
            job_description="Senior Python Developer...",
            output_path="/tmp/job_videos",
            output_format="mp4"
        )
        print(f"Video saved to: {video_path}")
    """
    from config import CACHE_DIR
    import shutil
    
    if output_format not in ["hls", "mp4"]:
        raise ValueError(f"output_format must be 'hls' or 'mp4', got '{output_format}'")
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"Generating Video from Job Description")
    print(f"{'='*60}")
    print(f"Output path: {output_path}")
    print(f"Output name: {output_name}")
    print(f"{'='*60}\n")
    
    # Step 1: Generate script
    print("\n--- STEP 1: GENERATING SCRIPT ---")
    generator = ScriptGenerator()
    script = generator.generate_script(job_description, force_regenerate=False)
    print(f"[OK] Script generated with {len(script['lines'])} lines")
    
    # Step 2: Generate TTS
    print("\n--- STEP 2: GENERATING TEXT-TO-SPEECH ---")
    script_cache_key = script.get("_cache_key", job_description)
    tts = TTSGenerator(topic=script_cache_key)
    audio_files = tts.generate_script_audio(script, force_regenerate=False)
    print(f"[OK] Generated {len(audio_files)} audio files")
    
    # Step 3: Compose video
    print("\n--- STEP 3: COMPOSING VIDEO ---")
    composer = VideoComposerFFmpeg(topic=script_cache_key)
    video_path = composer.compose_video(audio_files, script, output_name=output_name, output_format=output_format)
    print(f"[OK] Video generated: {video_path}")
    
    # Copy all outputs to output_path
    print(f"\n--- COPYING OUTPUTS TO {output_path} ---")
    topic_dirs = get_topic_dirs(script_cache_key)
    
    # Copy script
    script_src = topic_dirs['scripts'] / "script.json"
    if script_src.exists():
        import json
        with open(script_src, 'r') as f:
            script_data = json.load(f)
        with open(output_path / "script.json", 'w') as f:
            json.dump(script_data, f, indent=2)
        print(f"[OK] Copied script.json")
    
    # Copy audio files
    audio_dir = output_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    for audio_file in topic_dirs['audio'].glob("*.mp3"):
        shutil.copy2(audio_file, audio_dir / audio_file.name)
    print(f"[OK] Copied {len(list(audio_dir.glob('*.mp3')))} audio files")
    
    # Copy video - format depends on output_format
    if output_format == "hls":
        # Copy HLS structure: hls/{video_id}/
        # video_path points to hls/{video_id}/master.m3u8
        # Only copy the specific video_id directory, not the entire hls/ tree
        hls_video_id_dir = Path(video_path).parent  # Go up from master.m3u8 to hls/{video_id}/
        hls_dst = output_path / "hls" / output_name
        if hls_video_id_dir.exists():
            hls_dst.parent.mkdir(parents=True, exist_ok=True)
            if hls_dst.exists():
                shutil.rmtree(hls_dst)
            shutil.copytree(hls_video_id_dir, hls_dst)
            print(f"[OK] Copied HLS directory structure")
            print(f"  `-- hls/{output_name}/")
            print(f"      |-- master.m3u8")
            print(f"      |-- poster.jpg")
            print(f"      `-- 720p/ (with .ts segments)")
        
        # Extract the actual master.m3u8 path
        final_video_path = hls_dst / "master.m3u8"
    else:
        # Copy MP4 file
        mp4_dst = output_path / f"{output_name}.mp4"
        if Path(video_path).exists():
            shutil.copy2(video_path, mp4_dst)
            print(f"[OK] Copied MP4 file")
            print(f"  `-- {output_name}.mp4")
        
        final_video_path = mp4_dst
    
    print(f"\n{'='*60}")
    format_name = "HLS" if output_format == "hls" else "MP4"
    print(f"SUCCESS! {format_name} Video generated and saved to:")
    print(f"  {final_video_path}")
    print(f"{'='*60}\n")
    
    return str(final_video_path)


if __name__ == "__main__":
    main()
