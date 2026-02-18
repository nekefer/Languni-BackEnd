from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import get_current_user_from_cookie
from src.auth import models as auth_models
from src.entities.user import User
from src.saved_videos.service import SavedVideoService
from src.saved_videos.models import (
    SaveVideoRequest,
    SaveVideoResponse,
    SavedVideosPage,
    CheckVideoResponse,
)
from src.videos.models import VideoResponse
from src.exceptions import ValidationError
from src.rate_limiter import limiter, RATE_LIMITS


router = APIRouter(prefix="/api/saved-videos", tags=["saved-videos"])


def get_current_user(
    token_data: auth_models.TokenData = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
) -> User:
    """Convert token data to User object"""
    user_id = token_data.get_uuid()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.post("", response_model=SaveVideoResponse)
@limiter.limit(RATE_LIMITS["saved_videos_save"])
async def save_video(
    request: Request,
    video_data: SaveVideoRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Save a video to user's library"""
    try:
        user_video = await SavedVideoService.save_video(db, current_user, video_data.youtube_video_id)

        db.refresh(user_video, ["video"])

        return SaveVideoResponse(
            id=user_video.id,
            video=VideoResponse.model_validate(user_video.video),
            saved_at=user_video.saved_at
        )
    except ValidationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("", response_model=SavedVideosPage)
@limiter.limit(RATE_LIMITS["saved_videos_get"])
async def get_saved_videos(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's saved videos with pagination."""
    try:
        user_videos, total = await SavedVideoService.get_user_videos(db, current_user, skip, limit)

        video_responses = []
        for user_video in user_videos:
            video_responses.append(SaveVideoResponse(
                id=user_video.id,
                video=VideoResponse.model_validate(user_video.video),
                saved_at=user_video.saved_at
            ))

        page = (skip // limit) + 1 if limit > 0 else 1

        return SavedVideosPage(
            videos=video_responses,
            total=total,
            page=page,
            page_size=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch saved videos")


@router.get("/check/{youtube_video_id}", response_model=CheckVideoResponse)
@limiter.limit(RATE_LIMITS["saved_videos_get"])
async def check_video_saved(
    request: Request,
    youtube_video_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if a video is already saved"""
    try:
        is_saved = await SavedVideoService.is_video_saved(db, current_user, youtube_video_id)
        return CheckVideoResponse(youtube_video_id=youtube_video_id, saved=is_saved)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to check video status")


@router.delete("/{youtube_video_id}")
@limiter.limit(RATE_LIMITS["saved_videos_delete"])
async def delete_saved_video(
    request: Request,
    youtube_video_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a video from user's library"""
    try:
        success = await SavedVideoService.delete_video(db, current_user, youtube_video_id)
        if not success:
            raise HTTPException(status_code=404, detail="Video not found in your library")

        return {"message": "Video removed from library"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete video")
