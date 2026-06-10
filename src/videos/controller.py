from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.database.core import get_db
from src.auth.service import CurrentUser, RequireVerified
from src.entities.user import User
from src.videos.models import VideoResponse, VideoCreate, VideoListResponse
from src.videos.service import VideoService

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("/recommended", response_model=VideoListResponse)
async def get_recommended_videos(
    token: CurrentUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Recommended videos based on user's learning preferences."""
    user = db.query(User).filter(User.id == token.get_uuid()).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.learning_language:
        raise HTTPException(
            status_code=400,
            detail="Please complete onboarding to get recommendations",
        )

    offset = (page - 1) * page_size
    items, total = VideoService.get_recommended_videos(
        db=db,
        learning_language=user.learning_language,
        topics=user.topics,
        difficulty_level=user.level,
        limit=page_size,
        offset=offset,
    )

    return VideoListResponse(videos=items, total=total, page=page, page_size=page_size)


@router.post("/from-youtube", response_model=VideoResponse)
async def create_video_from_youtube(
    payload: VideoCreate,
    token: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Create a video entry by fetching metadata from YouTube.
    TODO: restrict to admin users when roles/permissions are available.
    """
    try:
        video = await VideoService.create_video_from_youtube(
            db=db,
            youtube_video_id=payload.youtube_video_id,
            topics=payload.topics,
            difficulty_level=payload.difficulty_level,
        )
        return video
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create video: {str(e)}")


@router.get("/{youtube_video_id}", response_model=VideoResponse)
async def get_video_by_youtube_id(
    youtube_video_id: str,
    db: Session = Depends(get_db),
):
    video = VideoService.get_video_by_youtube_id(db, youtube_video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/{youtube_video_id}/start-watching")
async def start_watching(
    youtube_video_id: str,
    token: RequireVerified,
    db: Session = Depends(get_db),
):
    """Call this when the player loads a video."""
    user = db.query(User).filter(User.id == token.get_uuid()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"allowed": True, "remaining": None}


@router.get("/", response_model=VideoListResponse)
async def list_videos(
    language: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * page_size
    items, total = VideoService.get_all_videos(
        db=db,
        language=language,
        limit=page_size,
        offset=offset,
    )
    return VideoListResponse(videos=items, total=total, page=page, page_size=page_size)
