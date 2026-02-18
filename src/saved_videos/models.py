from pydantic import BaseModel, validator
from datetime import datetime
from typing import Optional, List
from src.videos.models import VideoResponse


class SaveVideoRequest(BaseModel):
    youtube_video_id: str

    @validator('youtube_video_id')
    def validate_youtube_video_id(cls, v):
        if not v or not v.strip():
            raise ValueError('YouTube video ID cannot be empty')
        return v.strip()


class SaveVideoResponse(BaseModel):
    id: int
    video: VideoResponse
    saved_at: datetime

    class Config:
        from_attributes = True


class SavedVideosPage(BaseModel):
    videos: List[SaveVideoResponse]
    total: int
    page: int
    page_size: int


class CheckVideoResponse(BaseModel):
    youtube_video_id: str
    saved: bool
