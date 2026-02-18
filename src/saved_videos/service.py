from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from src.entities.video import Video
from src.entities.user_video import UserVideo
from src.entities.user import User
from src.youtube.service import get_video_metadata
from src.exceptions import ValidationError


class SavedVideoService:

    @staticmethod
    async def save_video(db: Session, user: User, youtube_video_id: str) -> UserVideo:
        """Save a video to user's library. Get-or-create the Video record first."""

        # Get or create the video in our database
        video = db.query(Video).filter(Video.youtube_video_id == youtube_video_id).first()
        if not video:
            metadata = await get_video_metadata(youtube_video_id)
            video = Video(
                youtube_video_id=youtube_video_id,
                title=metadata["title"],
                url=f"https://www.youtube.com/watch?v={youtube_video_id}",
                thumbnail_url=metadata.get("thumbnail"),
                language=metadata.get("language", "en"),
            )
            db.add(video)
            db.flush()

        # Check if already saved
        existing = db.query(UserVideo).filter(
            UserVideo.user_id == user.id,
            UserVideo.video_id == video.id
        ).first()

        if existing:
            raise ValidationError("Video is already saved")

        user_video = UserVideo(
            user_id=user.id,
            video_id=video.id,
        )

        try:
            db.add(user_video)
            db.commit()
            db.refresh(user_video)
            return user_video
        except IntegrityError:
            db.rollback()
            raise ValidationError("Failed to save video due to database constraint")

    @staticmethod
    async def get_user_videos(db: Session, user: User, skip: int = 0, limit: int = 12) -> tuple[list[UserVideo], int]:
        """Get user's saved videos with video details, plus total count."""
        total = (
            db.query(UserVideo)
            .filter(UserVideo.user_id == user.id)
            .count()
        )

        items = (
            db.query(UserVideo)
            .options(joinedload(UserVideo.video))
            .filter(UserVideo.user_id == user.id)
            .order_by(UserVideo.saved_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    async def is_video_saved(db: Session, user: User, youtube_video_id: str) -> bool:
        """Check if user has saved a video."""
        result = db.query(UserVideo).join(Video).filter(
            UserVideo.user_id == user.id,
            Video.youtube_video_id == youtube_video_id
        ).first()

        return result is not None

    @staticmethod
    async def delete_video(db: Session, user: User, youtube_video_id: str) -> bool:
        """Remove a video from user's library."""
        user_video = db.query(UserVideo).join(Video).filter(
            UserVideo.user_id == user.id,
            Video.youtube_video_id == youtube_video_id
        ).first()

        if not user_video:
            return False

        db.delete(user_video)
        db.commit()
        return True
