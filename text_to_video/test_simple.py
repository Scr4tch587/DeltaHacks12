#!/usr/bin/env python
"""
Simple test script to generate a video from job description text.
Tests HLS output structure: hls/{video_id}/master.m3u8
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from main import generate_video_from_text

if __name__ == "__main__":
    # Example job description
    job_description = """
    Senior Python Backend Developer
    
    We are looking for an experienced Python developer to lead our backend team.
    
    Requirements:
    - 5+ years Python development
    - FastAPI or Django experience
    - PostgreSQL and Redis
    - Docker and Kubernetes
    
    Responsibilities:
    - Design and implement scalable backend systems
    - Lead technical discussions
    - Mentor junior developers
    - Deploy and maintain production systems
    """
    
    # Output path where HLS files will be stored
    output_path = Path(__file__).parent / "hls_output"
    output_path.mkdir(exist_ok=True)
    
    # Generate video (returns path to hls/{video_id}/master.m3u8)
    master_playlist = generate_video_from_text(
        job_description=job_description.strip(),
        output_path=str(output_path),
        output_name="senior_python_dev"
    )
    
    print(f"\n{'='*60}")
    print(f"HLS Video generated successfully!")
    print(f"{'='*60}")
    print(f"Master Playlist: {master_playlist}")
    print(f"\nOutput structure:")
    print(f"  hls_output/")
    print(f"  `-- hls/")
    print(f"      `-- senior_python_dev/")
    print(f"          |-- master.m3u8")
    print(f"          |-- poster.jpg")
    print(f"          `-- 720p/")
    print(f"              |-- index.m3u8")
    print(f"              |-- seg_000.ts")
    print(f"              |-- seg_001.ts")
    print(f"              `-- ...")
    print(f"{'='*60}")
