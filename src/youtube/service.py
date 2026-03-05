import httpx
import asyncio
from typing import Optional
from fastapi import HTTPException
from cachetools import TTLCache
from sqlalchemy.orm import Session
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    PoTokenRequired,
    RequestBlocked,
    VideoUnplayable,
)
from .models import LikedVideo, TrendingVideo, TrendingVideosResponse
from ..config import get_settings
from ..entities.video import Video
import logging


_TRENDING_CACHE = TTLCache(maxsize=128, ttl=900)   # 15-minute TTL
_CAPTIONS_CACHE = TTLCache(maxsize=200, ttl=3600)  # 1-hour TTL

logger = logging.getLogger("youtube.service")


def _to_caption_dicts(fetched) -> list[dict]:
    return [{"text": item.text, "start": item.start, "duration": item.duration} for item in fetched]


def _fetch_captions_with_priority(video_id: str, languages: list[str]) -> tuple[list[dict], str] | None:
    """
    Fetch captions by listing transcripts once, then trying languages in priority order.
    Returns (captions, language) or None if no language matched.
    """
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)
    except TranscriptsDisabled:
        raise HTTPException(status_code=404, detail="Captions are disabled for this video")
    except VideoUnavailable:
        raise HTTPException(status_code=404, detail="Video not found or unavailable")
    except (PoTokenRequired, RequestBlocked):
        raise HTTPException(status_code=503, detail="Captions temporarily unavailable — YouTube is blocking server-side requests for this video")
    except VideoUnplayable:
        raise HTTPException(status_code=404, detail="Video is unplayable")
    except Exception as exc:
        logger.error(f"Unexpected error fetching transcript list for {video_id}: {exc}")
        raise HTTPException(status_code=503, detail="Captions temporarily unavailable")

    for lang in languages:
        try:
            captions = _to_caption_dicts(transcript_list.find_transcript([lang]).fetch())
            return captions, lang
        except NoTranscriptFound:
            logger.info(f"No [{lang}] captions for {video_id}, trying next")
            continue
        except (PoTokenRequired, RequestBlocked) as exc:
            logger.warning(f"YouTube blocked transcript fetch for {video_id} [{lang}]: {exc}")
            raise HTTPException(status_code=503, detail="Captions temporarily unavailable — YouTube is blocking server-side requests for this video")
        except Exception as exc:
            logger.error(f"Error fetching transcript for {video_id} [{lang}]: {exc}")
            continue

    return None


def _build_language_priority(
    learning_language: str | None,
    native_language: str | None,
) -> list[str]:
    """Deduplicated ordered list: [learning_language, native_language, 'en']."""
    seen: set[str] = set()
    priority: list[str] = []
    for lang in [learning_language, native_language, "en"]:
        if lang and lang not in seen:
            seen.add(lang)
            priority.append(lang)
    return priority



async def get_video_metadata(video_id: str) -> dict:
    """
    Fetch video metadata from YouTube Data API v3.
    Returns a dict with title, thumbnail, language, description, published_at.
    """
    settings = get_settings()
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,contentDetails",
        "id": video_id,
        "key": settings.youtube_api_key,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
    if response.status_code != 200:
        logger.error(f"YouTube metadata error for {video_id}: {response.text}")
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch video metadata")
    data = response.json()
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Video not found on YouTube")
    item = items[0]
    snippet = item.get("snippet", {})
    title = snippet.get("title", "")
    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
    language = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or "en"
    description = snippet.get("description", "")
    published_at = snippet.get("publishedAt")

    return {
        "title": title,
        "thumbnail": thumbnail_url,
        "language": language,
        "description": description,
        "published_at": published_at,
    }


async def get_video_captions(
    video_id: str,
    learning_language: str | None = None,
    native_language: str | None = None,
    db: Session | None = None,
) -> dict:
    """
    Fetch captions for a YouTube video, trying languages in priority order:
      1. learning_language  2. native_language  3. English

    Sources tried per language: DB → TTL cache → YouTube Transcript API.
    """
    languages = _build_language_priority(learning_language, native_language)

    # 1) DB: return stored subtitles if they match a preferred language
    if db is not None:
        video = db.query(Video).filter(Video.youtube_video_id == video_id).first()
        if video and video.subtitles and video.language in languages:
            logger.info(f"DB hit: {video_id} [{video.language}]")
            return {"video_id": video_id, "language": video.language, "captions": video.subtitles}

    # 2) Check cache first for any preferred language
    for lang in languages:
        cache_key = (video_id, lang)
        if cache_key in _CAPTIONS_CACHE:
            logger.debug(f"Cache hit: {video_id} [{lang}]")
            return _CAPTIONS_CACHE[cache_key]

    # 3) Single YouTube call: list transcripts once, try all languages
    fetched = _fetch_captions_with_priority(video_id, languages)
    if fetched is not None:
        captions, lang = fetched
        result = {"video_id": video_id, "language": lang, "captions": captions}
        _CAPTIONS_CACHE[(video_id, lang)] = result
        logger.info(f"Fetched {len(captions)} captions for {video_id} [{lang}]")

        # Persist captions to DB if the video record exists
        if db is not None:
            db_video = db.query(Video).filter(Video.youtube_video_id == video_id).first()
            if db_video and not db_video.subtitles:
                db_video.subtitles = captions
                db_video.language = lang
                db.commit()
                logger.info(f"Persisted captions to DB for {video_id} [{lang}]")

        return result

    raise HTTPException(
        status_code=404,
        detail="No captions available in your learning language, native language, or English",
    )


async def get_last_liked_video(google_access_token: str) -> LikedVideo:
    """
    Fetch the last video liked by the user using the YouTube Data API (async with httpx).
    """
    playlist_id = "LL"
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": 1
    }
    headers = {
        "Authorization": f"Bearer {google_access_token}"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch liked videos")
    items = response.json().get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="No liked videos found")
    video = items[0]["snippet"]
    return LikedVideo(
        video_id=video["resourceId"]["videoId"],
        title=video["title"],
        description=video["description"],
        thumbnails=video["thumbnails"]
    )


async def get_trending_videos(
    region: str = "US",
    max_results: int = 20,
    page_token: Optional[str] = None,
    category_id: Optional[str] = None
) -> TrendingVideosResponse:
    """
    Fetch trending videos from YouTube Data API v3.
    Uses in-memory caching with 15-minute TTL.
    
    Args:
        region: ISO 3166-1 alpha-2 country code (e.g., "US", "GB", "JP")
        max_results: Number of results to return (1-50)
        page_token: Token for pagination
        category_id: Optional category filter (e.g., "10" for Music)
    
    Returns:
        TrendingVideosResponse with items, pagination token, and metadata
    """
    settings = get_settings()
    
    # Generate cache key as a tuple to avoid collisions
    # (prevents "None" string from conflicting with None value)
    cache_key = (region, max_results, page_token, category_id)
    
    # Check cache (TTLCache handles expiration automatically)
    if cache_key in _TRENDING_CACHE:
        logger.info(f"Trending cache HIT key={cache_key}")
        return _TRENDING_CACHE[cache_key]
    
    # Build request
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": min(max_results, 50),
        "key": settings.youtube_api_key
    }
    
    if page_token:
        params["pageToken"] = page_token
    if category_id:
        params["videoCategoryId"] = category_id
    
    # Make API request with retry logic (reuse a single HTTP client)
    max_retries = 3
    retry_delay = 1.5

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                response = await client.get(url, params=params, timeout=10.0)

                if response.status_code == 200:
                    data = response.json()

                    # Parse videos
                    videos = []
                    for item in data.get("items", []):
                        snippet = item["snippet"]
                        videos.append(TrendingVideo(
                            video_id=item["id"],
                            title=snippet["title"],
                            description=snippet["description"],
                            thumbnails=snippet["thumbnails"],
                            channel_title=snippet["channelTitle"],
                            published_at=snippet["publishedAt"]
                        ))

                    # Build response
                    result = TrendingVideosResponse(
                        items=videos,
                        next_page_token=data.get("nextPageToken"),
                        region=region,
                        category=category_id
                    )

                    # Cache result (TTLCache handles expiration and size limits)
                    _TRENDING_CACHE[cache_key] = result
                    logger.info(f"Trending cache SET key={cache_key}")

                    
                    return result

                elif response.status_code == 429:  # Rate limit
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        raise HTTPException(
                            status_code=429,
                            detail="YouTube API rate limit exceeded. Please try again later."
                        )

                else:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"YouTube API error: {response.text}"
                    )

            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Failed to connect to YouTube API: {str(e)}"
                    )
    
    # Should never reach here, but just in case
    raise HTTPException(status_code=500, detail="Unexpected error fetching trending videos")

