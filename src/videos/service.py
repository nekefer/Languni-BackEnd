from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from src.entities.video import Video
from src.youtube.service import get_video_metadata


class VideoService:
    """Service for managing videos stored in the local database."""

    @staticmethod
    async def create_video_from_youtube(
        db: Session,
        youtube_video_id: str,
        topics: Optional[List[str]] = None,
        difficulty_level: Optional[str] = None,
    ) -> Video:
        """
        Import a video by fetching metadata from YouTube and persisting it.
        Raises ValueError if the video already exists.
        """
        existing = (
            db.query(Video)
            .filter(Video.youtube_video_id == youtube_video_id)
            .first()
        )
        if existing:
            raise ValueError("Video already exists in database")

        metadata = await get_video_metadata(youtube_video_id)

        video = Video(
            youtube_video_id=youtube_video_id,
            title=metadata["title"],
            url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            thumbnail_url=metadata.get("thumbnail"),
            language=metadata.get("language", "en"),
            topics=topics or [],
            difficulty_level=difficulty_level,
        )

        db.add(video)
        db.commit()
        db.refresh(video)
        return video

    @staticmethod
    def get_recommended_videos(
        db: Session,
        learning_language: str,
        topics: Optional[List[str]] = None,
        difficulty_level: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Video], int]:
        """Return videos filtered by language/topics/level, plus total count."""
        query = db.query(Video).filter(Video.language == learning_language, Video.publication_status == "published", Video.subtitles.isnot(None))

        if topics:
            # Overlap matches any of the topics in PostgreSQL arrays
            query = query.filter(Video.topics.overlap(topics))

        if difficulty_level:
            query = query.filter(Video.difficulty_level == difficulty_level)

        total = query.count()
        items = (
            query.order_by(Video.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    def get_video_by_youtube_id(db: Session, youtube_id: str) -> Optional[Video]:
        return (
            db.query(Video)
            .filter(Video.youtube_video_id == youtube_id)
            .first()
        )

    @staticmethod
    def get_all_videos(
        db: Session,
        language: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Video], int]:
        query = db.query(Video).filter(Video.publication_status == "published", Video.subtitles.isnot(None))
        if language:
            query = query.filter(Video.language == language)
        total = query.count()
        items = (
            query.order_by(Video.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total
