from fastapi import APIRouter, Cookie, HTTPException, Query, Depends, Request
from typing import Optional, Annotated
from .service import get_last_liked_video, get_trending_videos, get_video_captions, get_curated_videos
from .models import LikedVideo, TrendingVideosResponse, CaptionsResponse
from ..auth.service import CurrentUser, get_valid_google_token, get_current_user_from_cookie, get_premium_user
from ..auth import models as auth_models
from ..database.core import get_db
from ..rate_limiter import limiter, RATE_LIMITS
from ..entities.user import User
from sqlalchemy.orm import Session
from ..config import get_settings, Settings

# Helper to get authenticated user
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

# 🔒 PROTECT ALL ENDPOINTS: Add dependencies to the router
router = APIRouter(
    prefix="/youtube",
    tags=["youtube"],
    dependencies=[Depends(get_current_user)]  # ← This protects EVERY endpoint!
)

@router.get("/trending", response_model=TrendingVideosResponse)
@limiter.limit(RATE_LIMITS["youtube_trending"])
async def trending_videos(
    request: Request,
    region: str = Query(default="US", description="ISO 3166-1 alpha-2 country code"),
    max_results: int = Query(default=25, ge=1, le=50, description="Number of results (1-50)"),
    page_token: Optional[str] = Query(default=None, description="Pagination token"),
    category_id: Optional[str] = Query(default=None, description="Category ID (e.g., '10' for Music)")
):
    """Get trending videos from YouTube. Available to all authenticated users."""
    return await get_trending_videos(
        region=region,
        max_results=max_results,
        page_token=page_token,
        category_id=category_id
    )


@router.get("/curated", response_model=TrendingVideosResponse)
@limiter.limit("30/minute")
async def curated_videos(
    request: Request,
    current_user: User = Depends(get_current_user),
    _: auth_models.TokenData = Depends(get_premium_user),
):
    """
    Get personalized video recommendations based on the user's learning language, level, and topics.
    Premium only.
    """
    if not current_user.learning_language or not current_user.level:
        raise HTTPException(
            status_code=400,
            detail="Please complete onboarding to access personalized recommendations."
        )

    return await get_curated_videos(
        learning_language=current_user.learning_language,
        level=current_user.level,
        topics=current_user.topics or [],
    )


@router.get("/{video_id}/captions", response_model=CaptionsResponse)
@limiter.limit(RATE_LIMITS["youtube_captions"])
async def get_captions(
    request: Request,
    video_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch captions for a YouTube video.

    Tries languages in order:
    1. User's learning language
    2. User's native language
    3. English (fallback)
    """
    return await get_video_captions(
        video_id,
        learning_language=current_user.learning_language,
        native_language=current_user.native_language,
        db=db,
    )


@router.get("/last-liked-video", response_model=LikedVideo)
@limiter.limit(RATE_LIMITS["youtube_liked"])
async def last_liked_video(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)]
):
    """
    SECURE: Endpoint to get the last video liked by the user.
    Automatically refreshes Google token if expired.
    """
    if not current_user.get_uuid():
        raise HTTPException(status_code=401, detail="User not authenticated")

    try:
        google_token = get_valid_google_token(db, current_user.get_uuid(), settings)
        return await get_last_liked_video(google_token)

    except Exception as e:
        if "No Google" in str(e) or "reconnect" in str(e):
            raise HTTPException(
                status_code=400,
                detail="Google account not connected. Please sign in with Google."
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch liked video: {str(e)}"
        )
