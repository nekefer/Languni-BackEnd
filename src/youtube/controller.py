from fastapi import APIRouter, Cookie, HTTPException, Query, Depends, Request
from typing import Optional, Annotated
from .service import get_last_liked_video, get_trending_videos, get_video_captions, get_curated_videos
from .models import LikedVideo, TrendingVideosResponse, CaptionsResponse, TrendingVideo
from ..videos.service import VideoService
from ..auth.service import CurrentUser, get_valid_google_token, get_current_user_from_cookie
from ..auth import models as auth_models
from ..database.core import get_db
from ..rate_limiter import limiter, RATE_LIMITS
from ..entities.user import User
from sqlalchemy.orm import Session
from ..config import get_settings, Settings
from ..exceptions import AuthenticationError

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

router = APIRouter(
    prefix="/youtube",
    tags=["youtube"],
)


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Return a user when auth cookies are present; otherwise allow guest use."""
    try:
        token_data = get_current_user_from_cookie(request, settings)
    except AuthenticationError:
        return None

    user_id = token_data.get_uuid()
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

@router.get("/trending", response_model=TrendingVideosResponse)
@limiter.limit(RATE_LIMITS["youtube_trending"])
async def trending_videos(
    request: Request,
    region: str = Query(default="US", description="ISO 3166-1 alpha-2 country code"),
    max_results: int = Query(default=25, ge=1, le=50, description="Number of results (1-50)"),
    page_token: Optional[str] = Query(default=None, description="Pagination token"),
    category_id: Optional[str] = Query(default=None, description="Category ID (e.g., '10' for Music)"),
    db: Session = Depends(get_db),
):
    """Return prepared library videos using the existing card response contract."""
    language = {"FR": "fr", "ES": "es", "US": "en", "GB": "en"}.get(region, "en")
    try:
        offset = int(page_token or "0")
        if offset < 0 or offset > 100000:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, "Invalid page token")
    items, total = VideoService.get_all_videos(db, language=language, limit=max_results, offset=offset)
    return catalog_response(items, str(offset + max_results) if offset + max_results < total else None, region)


def catalog_response(items, next_page_token=None, region="US"):
    return TrendingVideosResponse(items=[TrendingVideo(
        video_id=video.youtube_video_id, title=video.title, description="",
        thumbnails={"high": {"url": video.thumbnail_url or f"https://i.ytimg.com/vi/{video.youtube_video_id}/hqdefault.jpg"}},
        channel_title=video.channel_title or "",
        published_at=video.youtube_published_at or video.created_at.isoformat(),
    ) for video in items], next_page_token=next_page_token, region=region, category=None)


@router.get("/curated", response_model=TrendingVideosResponse)
@limiter.limit("30/minute")
async def curated_videos(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get personalized video recommendations based on the user's learning language, level, and topics.
    Available to all authenticated users.
    """
    if not current_user.learning_language or not current_user.level:
        raise HTTPException(
            status_code=400,
            detail="Please complete onboarding to access personalized recommendations."
        )

    items, _ = VideoService.get_recommended_videos(
        db=db,
        learning_language=current_user.learning_language,
        difficulty_level=current_user.level,
        topics=current_user.topics or [],
        limit=24,
    )
    return catalog_response(items)


@router.get("/{video_id}/captions", response_model=CaptionsResponse)
@limiter.limit(RATE_LIMITS["youtube_captions"])
async def get_captions(
    request: Request,
    video_id: str,
    native_language: Optional[str] = Query(default=None, description="Language to translate into for guests"),
    learning_language: Optional[str] = Query(default=None, description="Preferred caption language for guests"),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
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
        learning_language=current_user.learning_language if current_user else learning_language,
        native_language=current_user.native_language if current_user else native_language,
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
