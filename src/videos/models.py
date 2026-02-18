from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field


class VideoBase(BaseModel):
    """Base video model corresponding to the Video entity."""
    youtube_video_id: str = Field(..., max_length=20)
    title: str
    url: str
    thumbnail_url: Optional[str] = None

    language: str = Field(..., max_length=10, description="Main spoken language of the video (e.g., en, fr, es)")

    topics: Optional[List[str]] = Field(None, description="Video topics (e.g., music, travel, business)")
    difficulty_level: Optional[str] = Field(None, max_length=20, description="beginner | intermediate | advanced")
    video_type: Optional[str] = Field(None, max_length=10, description="short (<=60s) or video (>60s)")


class VideoCreate(BaseModel):
    """Payload for creating video by importing from YouTube."""
    youtube_video_id: str = Field(..., max_length=20)
    topics: Optional[List[str]] = None
    difficulty_level: Optional[str] = None


class VideoResponse(VideoBase):
    """Video response including ID and timestamps."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    """Paginated list of videos with metadata."""
    videos: List[VideoResponse]
    total: int
    page: int
    page_size: int
