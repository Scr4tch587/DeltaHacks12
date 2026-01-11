#!/usr/bin/env python
"""
Test script to generate MP4 video from job description text.
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
    
    # Output path where files will be stored
    output_path = Path(__file__).parent / "mp4_output"
    output_path.mkdir(exist_ok=True)
    
    # Generate MP4 video
    video_path = generate_video_from_text(
        job_description=job_description.strip(),
        output_path=str(output_path),
        output_format="mp4"
    )
    
    print(f"\n{'='*60}")
    print(f"MP4 Video generated successfully!")
    print(f"{'='*60}")
    print(f"Video file: {video_path}")
    print(f"{'='*60}")
