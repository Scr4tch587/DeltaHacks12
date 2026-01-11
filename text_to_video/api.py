"""
Simple text-to-video API endpoint.

This module provides a FastAPI endpoint that generates videos from job descriptions.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import sys
from pathlib import Path

# Add text_to_video to path
sys.path.insert(0, str(Path(__file__).parent.parent / "text_to_video"))

from main import generate_video_from_text

app = FastAPI(title="Text-to-Video Generator")


class VideoRequest(BaseModel):
    """Request model for video generation"""
    job_description: str = Field(
        ...,
        min_length=50,
        description="Job description text"
    )
    output_path: Optional[str] = Field(
        default=None,
        description="Where to save output (default: /tmp/videos)"
    )
    output_name: Optional[str] = Field(
        default="video",
        description="Output video filename (without .mp4)"
    )


class VideoResponse(BaseModel):
    """Response model for video generation"""
    status: str
    video_path: str
    message: str


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "text-to-video"}


@app.post("/generate", response_model=VideoResponse)
async def generate_video(request: VideoRequest):
    """
    Generate a video from job description text.
    
    Args:
        job_description: The job description text
        output_path: Optional output directory
        output_name: Optional output filename
    
    Returns:
        Path to generated video
    """
    try:
        output_path = request.output_path or "/tmp/videos"
        output_name = request.output_name or "video"
        
        video_path = generate_video_from_text(
            job_description=request.job_description,
            output_path=output_path,
            output_name=output_name
        )
        
        return VideoResponse(
            status="success",
            video_path=video_path,
            message="Video generated successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Video generation failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
