from sqlalchemy import Column, Integer, String, ARRAY, DateTime, Index
from sqlalchemy.sql import func
from src.database.core import Base


class Video(Base):
    """
    Video entity for storing YouTube videos with metadata
    Used for video recommendations based on user preferences
    """
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    youtube_video_id = Column(String(20), unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=False)
    thumbnail_url = Column(String, nullable=True)
    
    # Language & Subtitles (fetched from YouTube API)
    language = Column(String(10), nullable=False, index=True)  # Main video language: "en", "fr", "es"
    available_subtitles = Column(ARRAY(String), nullable=True)  # Available subtitle languages: ["en", "fr", "es"]
    
    # Metadata (set manually or by AI)
    topics = Column(ARRAY(String), nullable=True)  # Video topics: ["music", "travel", "business"]
    difficulty_level = Column(String(20), nullable=True)  # Learning difficulty: "beginner", "intermediate", "advanced"
    video_type = Column(String(10), nullable=True)  # "short" (<= 60s) or "video" (> 60s)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # PostgreSQL GIN index for efficient array search on topics
    __table_args__ = (
        Index('idx_videos_topics', 'topics', postgresql_using='gin'),
    )

    def __repr__(self):
        return f"<Video(id={self.id}, youtube_id='{self.youtube_video_id}', title='{self.title[:30]}...', language='{self.language}')>"
