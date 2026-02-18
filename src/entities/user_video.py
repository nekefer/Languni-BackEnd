from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.database.core import Base
from datetime import datetime


class UserVideo(Base):
    __tablename__ = "user_videos"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    saved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="user_videos")
    video = relationship("Video")

    # Ensure user can't save same video twice
    __table_args__ = (
        UniqueConstraint('user_id', 'video_id', name='unique_user_video'),
    )
