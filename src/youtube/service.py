import httpx
import asyncio
from typing import Optional
from fastapi import HTTPException
from cachetools import TTLCache
from functools import lru_cache
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from .models import LikedVideo, TrendingVideo, TrendingVideosResponse
from ..config import get_settings
import logging


# Cache for trending videos (15-minute TTL, max 128 entries)
_TRENDING_CACHE = TTLCache(maxsize=128, ttl=900)

# Cache for captions (1 hour TTL, max 100 entries)
_CAPTIONS_CACHE = TTLCache(maxsize=100, ttl=3600)

logger = logging.getLogger("youtube.trending")

@lru_cache(maxsize=100)
def _fetch_captions_cached(video_id: str, language: str):
    """
    Fetch and cache captions. LRU cache keeps last 100 videos.
    Captions rarely change, so caching is safe.
    """
    api = YouTubeTranscriptApi()
    
    # Get available transcripts
    transcript_list = api.list(video_id)
    available_transcripts = list(transcript_list)
    
    # Try to find the requested language
    for transcript in available_transcripts:
        if transcript.language_code == language:
            fetched = transcript.fetch()
            # Convert FetchedTranscript to list of dicts
            return [{"text": item.text, "start": item.start, "duration": item.duration} 
                   for item in fetched]
    
    # Fallback to English if not found
    if language != 'en':
        for transcript in available_transcripts:
            if transcript.language_code == 'en':
                fetched = transcript.fetch()
                return [{"text": item.text, "start": item.start, "duration": item.duration} 
                       for item in fetched]
    
    # Use first available transcript
    if available_transcripts:
        first_transcript = available_transcripts[0]
        fetched = first_transcript.fetch()
        return [{"text": item.text, "start": item.start, "duration": item.duration} 
               for item in fetched]
    
    # If nothing found, try simple fetch (this shouldn't happen)
    fetched = api.fetch(video_id)
    return [{"text": item.text, "start": item.start, "duration": item.duration} 
           for item in fetched]

async def _get_available_subtitles(video_id: str) -> list[str]:
    """
    Get available subtitle languages for a YouTube video via Captions API.
    Returns a list of language codes, e.g., ["en", "fr"].
    """
    settings = get_settings()
    url = "https://www.googleapis.com/youtube/v3/captions"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": settings.youtube_api_key,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
    if response.status_code != 200:
        logger.warning(f"Failed to fetch captions list for {video_id}: {response.text}")
        return []
    data = response.json()
    languages = [item["snippet"].get("language") for item in data.get("items", [])]
    return [lang for lang in languages if lang]


async def get_video_metadata(video_id: str) -> dict:
    """
    Fetch video metadata from YouTube Data API v3.
    Returns a dict with title, thumbnail, language, available_subtitles, description, published_at.
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

    available_subtitles = await _get_available_subtitles(video_id)

    return {
        "title": title,
        "thumbnail": thumbnail_url,
        "language": language,
        "available_subtitles": available_subtitles,
        "description": description,
        "published_at": published_at,
    }


async def get_video_captions(video_id: str, language: str = 'en'):
    """
    Fetch captions for a YouTube video.
    
    Args:
        video_id: YouTube video ID
        language: Language code (e.g., 'en', 'es', 'fr')
        
    Returns:
        Dict with video_id, language, and captions data
        
    Raises:
        HTTPException: If captions unavailable or video not found
    """
    cache_key = (video_id, language)
    
    # Check cache first
    if cache_key in _CAPTIONS_CACHE:
        logger.debug(f"Returning cached captions for {video_id}")
        return _CAPTIONS_CACHE[cache_key]
    
    try:
        logger.info(f"Fetching captions for video {video_id}, language: {language}")
        
        # Fetch from YouTube
        captions = _fetch_captions_cached(video_id, language)
        
        result = {
            "video_id": video_id,
            "language": language,
            "captions": captions
        }
        
        # Cache the result
        _CAPTIONS_CACHE[cache_key] = result
        
        logger.info(f"Successfully fetched {len(captions)} captions for {video_id}")
        return result
        
    except TranscriptsDisabled:
        logger.warning(f"Captions disabled for video {video_id}")
        raise HTTPException(
            status_code=404,
            detail="Captions are disabled for this video"
        )
    except NoTranscriptFound:
        logger.warning(f"No captions found for video {video_id} in language {language}")
        raise HTTPException(
            status_code=404,
            detail=f"No captions available in language: {language}"
        )
    except VideoUnavailable:
        logger.warning(f"Video {video_id} not found or unavailable")
        raise HTTPException(
            status_code=404,
            detail="Video not found or unavailable"
        )
    except Exception as e:
        logger.error(f"Failed to fetch captions for {video_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch captions: {str(e)}"
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

