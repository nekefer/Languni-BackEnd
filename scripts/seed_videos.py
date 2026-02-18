"""
Seed the videos table by fetching YouTube videos and auto-classifying
their topic and language using YouTube's own metadata.

Usage:
    cd Linguini-BackEnd
    python -m scripts.seed_videos                # full seed (all topics + languages)
    python -m scripts.seed_videos --dry-run      # preview without writing to DB
    python -m scripts.seed_videos --language en   # seed only English videos
    python -m scripts.seed_videos --topic food    # seed only food-related videos
    python -m scripts.seed_videos --count 10      # 10 videos per combo (default 5)
"""

import asyncio
import argparse
import logging
import re
import sys
import os

import httpx
from sqlalchemy.orm import Session
from youtube_transcript_api import YouTubeTranscriptApi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings
from src.database.core import SessionLocal
from src.entities.video import Video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("seed_videos")


class QuotaExhausted(Exception):
    """Raised when the YouTube API quota is exceeded (403)."""
    pass

# ---------------------------------------------------------------------------
# Constants — must match frontend onboarding (src/utils/onboarding.js)
# ---------------------------------------------------------------------------

LANGUAGES = ["en", "fr", "es"]

TOPICS = [
    "music", "travel", "food", "sports", "technology", "business",
    "entertainment", "science", "culture", "news", "education", "lifestyle",
]

VIDEOS_PER_COMBO = 5

# Region codes used to get videos in each language
LANG_TO_REGION = {"en": "US", "fr": "FR", "es": "ES"}

# Year ranges for fetching older popular videos
OLDER_YEAR_RANGES = [
    ("2021-01-01T00:00:00Z", "2021-12-31T23:59:59Z"),
    ("2022-01-01T00:00:00Z", "2022-12-31T23:59:59Z"),
    ("2023-01-01T00:00:00Z", "2023-12-31T23:59:59Z"),
    ("2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"),
    ("2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
]

# ---------------------------------------------------------------------------
# YouTube categoryId → user topic mapping
# ---------------------------------------------------------------------------

CATEGORY_TO_TOPIC: dict[str, list[str]] = {
    "1":  ["entertainment"],        # Film & Animation
    "2":  ["technology"],            # Autos & Vehicles
    "10": ["music"],                 # Music
    "15": ["lifestyle"],             # Pets & Animals
    "17": ["sports"],                # Sports
    "19": ["travel"],                # Travel & Events
    "20": ["entertainment"],         # Gaming
    "22": ["lifestyle"],             # People & Blogs
    "23": ["entertainment"],         # Comedy
    "24": ["entertainment"],         # Entertainment
    "25": ["news"],                  # News & Politics
    "26": ["lifestyle"],             # Howto & Style
    "27": ["education"],             # Education
    "28": ["technology", "science"], # Science & Technology
    "29": ["culture"],               # Nonprofits & Activism
}

# Topics that have a direct YouTube category — we fetch with mostPopular
CATEGORY_TOPICS: dict[str, str] = {
    "music":         "10",
    "sports":        "17",
    "travel":        "19",
    "entertainment": "24",
    "news":          "25",
    "lifestyle":     "26",
    "education":     "27",
    "technology":    "28",
    "science":       "28",
}

# Search queries used for category-based topics when fetching older videos
CATEGORY_SEARCH_QUERIES: dict[str, dict[str, list[str]]] = {
    "music":         {"en": ["popular music"],         "fr": ["musique populaire"],         "es": ["musica popular"]},
    "sports":        {"en": ["sports highlights"],     "fr": ["sport highlights"],          "es": ["deportes highlights"]},
    "travel":        {"en": ["travel vlog destination"], "fr": ["voyage vlog destination"],   "es": ["viaje vlog destino"]},
    "entertainment": {"en": ["entertainment"],         "fr": ["divertissement"],            "es": ["entretenimiento"]},
    "news":          {"en": ["news report"],           "fr": ["actualites"],                "es": ["noticias"]},
    "lifestyle":     {"en": ["lifestyle tips"],        "fr": ["style de vie"],              "es": ["estilo de vida"]},
    "education":     {"en": ["educational"],           "fr": ["educatif"],                  "es": ["educativo"]},
    "technology":    {"en": ["tech review"],           "fr": ["technologie"],               "es": ["tecnologia"]},
    "science":       {"en": ["science explained"],     "fr": ["science expliquee"],         "es": ["ciencia explicada"]},
}

# Topics without a direct YouTube category — we use search queries
SEARCH_TOPICS: dict[str, dict[str, list[str]]] = {
    "food": {
        "en": ["cooking recipe tutorial", "food review english", "chef cooking english"],
        "fr": ["recette cuisine francaise", "cuisine francaise", "gastronomie francais"],
        "es": ["receta cocina espanola", "cocina latinoamericana", "gastronomia espanol"],
    },
    "business": {
        "en": ["business tips entrepreneurship", "finance investing explained", "startup business english"],
        "fr": ["business entrepreneuriat francais", "finance investissement francais", "entreprise francais"],
        "es": ["negocios emprendimiento espanol", "finanzas inversion espanol", "empresa espanol"],
    },
    "culture": {
        "en": ["cultural history documentary", "world culture traditions", "art history english"],
        "fr": ["culture histoire documentaire francais", "traditions culturelles francais", "art histoire francais"],
        "es": ["cultura historia documental espanol", "tradiciones culturales espanol", "arte historia espanol"],
    },
}

# ---------------------------------------------------------------------------
# topicDetails Wikipedia URL → user topic mapping
# ---------------------------------------------------------------------------

WIKI_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "music":         ["music", "song", "singer", "musician", "hip_hop", "rock_music", "pop_music", "jazz", "classical_music"],
    "travel":        ["travel", "tourism", "tourist", "vacation", "destination"],
    "food":          ["food", "cooking", "cuisine", "restaurant", "chef", "recipe", "baking", "gastronomy"],
    "sports":        ["sport", "football", "soccer", "basketball", "tennis", "athletics", "olympic", "cricket", "baseball"],
    "technology":    ["technology", "computer", "software", "hardware", "internet", "artificial_intelligence", "programming", "smartphone"],
    "business":      ["business", "finance", "economics", "entrepreneurship", "marketing", "investment", "stock_market", "management"],
    "entertainment": ["entertainment", "film", "television", "movie", "comedy", "drama", "animation", "gaming", "video_game"],
    "science":       ["science", "physics", "chemistry", "biology", "astronomy", "mathematics", "research", "experiment"],
    "culture":       ["culture", "society", "history", "art", "religion", "philosophy", "museum", "heritage", "tradition"],
    "news":          ["news", "politics", "government", "election", "journalism", "media"],
    "education":     ["education", "university", "school", "learning", "teaching", "academic", "lecture"],
    "lifestyle":     ["lifestyle", "health", "fitness", "fashion", "beauty", "wellness", "yoga", "meditation", "pet"],
}


# ---------------------------------------------------------------------------
# ISO 8601 duration parsing & video_type detection
# ---------------------------------------------------------------------------

_ISO8601_RE = re.compile(
    r"^P"
    r"(?:(\d+)D)?"
    r"(?:T"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+)S)?"
    r")?$"
)


def parse_iso8601_duration(duration: str) -> int:
    """Parse an ISO 8601 duration string (e.g. 'PT5M12S') into total seconds."""
    m = _ISO8601_RE.match(duration or "")
    if not m:
        return 0
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def detect_video_type(item: dict) -> str:
    """Return 'short' if video is <= 60 seconds, otherwise 'video'."""
    duration_str = item.get("contentDetails", {}).get("duration", "")
    total_seconds = parse_iso8601_duration(duration_str)
    return "short" if 0 < total_seconds <= 60 else "video"


# ---------------------------------------------------------------------------
# Topic classification
# ---------------------------------------------------------------------------

def classify_topics(category_id: str, topic_categories: list[str], title: str, description: str) -> list[str]:
    """
    Determine which user topics a video belongs to using 3 signals:
      1. YouTube categoryId
      2. topicDetails.topicCategories (Wikipedia URLs)
      3. Keyword matching on title + description
    """
    topics: set[str] = set()

    # 1) categoryId mapping
    if category_id and category_id in CATEGORY_TO_TOPIC:
        topics.update(CATEGORY_TO_TOPIC[category_id])

    # 2) topicDetails Wikipedia URLs
    for url in topic_categories:
        url_lower = url.lower()
        for topic, keywords in WIKI_TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in url_lower:
                    topics.add(topic)
                    break

    # 3) Keyword matching on title + description (fallback for food, business, culture)
    text = f"{title} {description}".lower()
    for topic in ["food", "business", "culture"]:
        if topic in topics:
            continue
        for kw in WIKI_TOPIC_KEYWORDS[topic]:
            if kw.replace("_", " ") in text:
                topics.add(topic)
                break

    return sorted(topics) if topics else ["entertainment"]


def detect_language(snippet: dict, region_hint: str) -> str:
    """Extract the video language from snippet metadata."""
    lang = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or ""
    # YouTube sometimes returns "en-US", "fr-FR" etc — normalize to 2-char code
    lang = lang[:2].lower()
    if lang in LANGUAGES:
        return lang
    # Fallback to region hint
    region_to_lang = {"US": "en", "GB": "en", "FR": "fr", "ES": "es"}
    return region_to_lang.get(region_hint, "en")


# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

async def fetch_popular_by_category(
    client: httpx.AsyncClient,
    api_key: str,
    category_id: str,
    region: str,
    max_results: int = 50,
) -> list[dict]:
    """
    Fetch most popular videos for a YouTube category in a region.
    Returns raw video items with snippet + topicDetails.
    """
    params = {
        "part": "snippet,topicDetails,contentDetails",
        "chart": "mostPopular",
        "videoCategoryId": category_id,
        "regionCode": region,
        "maxResults": min(max_results, 50),
        "key": api_key,
    }
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params=params,
        timeout=15.0,
    )
    if resp.status_code == 403:
        logger.error("YouTube API quota exhausted — stopping all requests")
        raise QuotaExhausted()
    if resp.status_code != 200:
        logger.error(
            "videos.list failed (cat=%s, region=%s): %s %s",
            category_id, region, resp.status_code, resp.text[:200],
        )
        return []
    return resp.json().get("items", [])


async def search_videos(
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    region: str,
    language: str,
    max_results: int = 15,
    published_after: str | None = None,
    published_before: str | None = None,
    order: str = "relevance",
) -> list[str]:
    """
    Search YouTube and return a list of video IDs.
    Filters for videos with closed captions.
    Supports date range filtering and sort order.
    """
    params = {
        "part": "id",
        "q": query,
        "type": "video",
        "videoCaption": "closedCaption",
        "regionCode": region,
        "relevanceLanguage": language,
        "maxResults": max_results,
        "order": order,
        "key": api_key,
    }
    if published_after:
        params["publishedAfter"] = published_after
    if published_before:
        params["publishedBefore"] = published_before
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/search",
        params=params,
        timeout=15.0,
    )
    if resp.status_code == 403:
        logger.error("YouTube API quota exhausted — stopping all requests")
        raise QuotaExhausted()
    if resp.status_code != 200:
        logger.error("search failed (q=%s): %s %s", query, resp.status_code, resp.text[:200])
        return []
    return [
        item["id"]["videoId"]
        for item in resp.json().get("items", [])
        if item.get("id", {}).get("videoId")
    ]


async def fetch_video_details(
    client: httpx.AsyncClient,
    api_key: str,
    video_ids: list[str],
) -> list[dict]:
    """Fetch full details (snippet + topicDetails + contentDetails) for a batch of video IDs."""
    if not video_ids:
        return []
    params = {
        "part": "snippet,topicDetails,contentDetails",
        "id": ",".join(video_ids[:50]),
        "key": api_key,
    }
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params=params,
        timeout=15.0,
    )
    if resp.status_code == 403:
        logger.error("YouTube API quota exhausted — stopping all requests")
        raise QuotaExhausted()
    if resp.status_code != 200:
        logger.error("videos.list detail fetch failed: %s %s", resp.status_code, resp.text[:200])
        return []
    return resp.json().get("items", [])


async def search_older_videos(
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    region: str,
    language: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Search for popular older videos across year ranges (2021-2025).
    Uses order=viewCount to get popular videos, not random ones.
    Returns full video detail items.
    """
    all_items: list[dict] = []
    per_year = max(1, max_results // len(OLDER_YEAR_RANGES))

    for published_after, published_before in OLDER_YEAR_RANGES:
        video_ids = await search_videos(
            client, api_key, query, region, language,
            max_results=per_year,
            published_after=published_after,
            published_before=published_before,
            order="viewCount",
        )
        if video_ids:
            items = await fetch_video_details(client, api_key, video_ids)
            all_items.extend(items)
        await asyncio.sleep(0.2)

        if len(all_items) >= max_results:
            break

    return all_items[:max_results]


# ---------------------------------------------------------------------------
# Subtitle fetching
# ---------------------------------------------------------------------------

def fetch_subtitles(video_id: str, language: str) -> list[dict] | None:
    """
    Fetch subtitles for a YouTube video using youtube_transcript_api.
    Returns a list of caption dicts or None on failure.
    """
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        available = list(transcript_list)

        # Try exact language match first
        for transcript in available:
            if transcript.language_code == language:
                fetched = transcript.fetch()
                return [{"text": item.text, "start": item.start, "duration": item.duration}
                        for item in fetched]

        # Fallback to first available transcript
        if available:
            fetched = available[0].fetch()
            logger.debug("  subtitle fallback: %s → %s for %s", language, available[0].language_code, video_id)
            return [{"text": item.text, "start": item.start, "duration": item.duration}
                    for item in fetched]

    except Exception as exc:
        logger.debug("  subtitle fetch failed for %s: %s", video_id, exc)

    return None


# ---------------------------------------------------------------------------
# Insert helper
# ---------------------------------------------------------------------------

def insert_video(db: Session, item: dict, region_hint: str, dry_run: bool, topic_override: list[str] | None = None) -> bool:
    """
    Classify and insert a single YouTube video item into the database.
    Returns True if a new row was inserted.
    """
    vid_id = item.get("id")
    if not vid_id:
        return False

    # Skip videos without subtitles
    has_caption = item.get("contentDetails", {}).get("caption", "false")
    if has_caption != "true":
        logger.debug("  skip %s — no subtitles available", vid_id)
        return False

    snippet = item.get("snippet", {})
    topic_details = item.get("topicDetails", {})
    topic_categories = topic_details.get("topicCategories", [])
    category_id = snippet.get("categoryId", "")

    title = snippet.get("title", "")
    description = snippet.get("description", "")
    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (
        thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
    ).get("url")

    language = detect_language(snippet, region_hint)
    topics = topic_override if topic_override else classify_topics(category_id, topic_categories, title, description)
    video_type = detect_video_type(item)

    if dry_run:
        logger.info(
            "  [DRY RUN] %s  lang=%-2s  type=%-5s  topics=%-30s  \"%s\"",
            vid_id, language, video_type, topics, title[:60],
        )
        return True

    # Skip duplicates
    exists = db.query(Video.id).filter(Video.youtube_video_id == vid_id).first()
    if exists:
        return False

    # Fetch subtitles for the video's language
    subs = fetch_subtitles(vid_id, language)

    video = Video(
        youtube_video_id=vid_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={vid_id}",
        thumbnail_url=thumbnail_url,
        language=language,
        topics=topics,
        difficulty_level=None,
        video_type=video_type,
        subtitles=subs,
    )
    db.add(video)
    try:
        db.commit()
        sub_count = len(subs) if subs else 0
        logger.info(
            "  + %s  lang=%-2s  type=%-5s  subs=%-4d  topics=%-30s  \"%s\"",
            vid_id, language, video_type, sub_count, topics, title[:60],
        )
        return True
    except Exception as exc:
        db.rollback()
        logger.warning("  insert failed %s: %s", vid_id, exc)
        return False


# ---------------------------------------------------------------------------
# Core seeding logic
# ---------------------------------------------------------------------------

async def seed_category_topic(
    client: httpx.AsyncClient,
    api_key: str,
    db: Session,
    topic: str,
    language: str,
    target_count: int,
    dry_run: bool,
) -> int:
    """Seed videos for a topic that has a direct YouTube category.
    Splits between trending (mostPopular) and older popular videos."""
    category_id = CATEGORY_TOPICS[topic]
    region = LANG_TO_REGION[language]

    trending_target = (target_count + 1) // 2  # ceil half for trending
    older_target = target_count - trending_target

    inserted = 0

    # --- Part 1: Trending videos from mostPopular ---
    items = await fetch_popular_by_category(client, api_key, category_id, region, max_results=50)
    if items:
        for item in items:
            if inserted >= trending_target:
                break
            if insert_video(db, item, region, dry_run):
                inserted += 1
    else:
        logger.warning("  No trending results for category %s in %s", category_id, region)

    # --- Part 2: Older popular videos via search ---
    queries = CATEGORY_SEARCH_QUERIES.get(topic, {}).get(language, [])
    if queries and older_target > 0:
        query = queries[0]
        logger.info("  Fetching older videos for %s/%s (query: %s)", topic, language, query)
        older_items = await search_older_videos(
            client, api_key, query, region, language, max_results=older_target * 3,
        )
        for item in older_items:
            if inserted >= target_count:
                break
            if insert_video(db, item, region, dry_run):
                inserted += 1

    return inserted


async def seed_search_topic(
    client: httpx.AsyncClient,
    api_key: str,
    db: Session,
    topic: str,
    language: str,
    target_count: int,
    dry_run: bool,
) -> int:
    """Seed videos for a topic that needs search queries (food, business, culture).
    Splits between recent and older popular videos."""
    queries = SEARCH_TOPICS.get(topic, {}).get(language, [])
    if not queries:
        return 0

    region = LANG_TO_REGION[language]
    recent_target = (target_count + 1) // 2
    older_target = target_count - recent_target

    inserted = 0

    # --- Part 1: Recent videos (no date filter, relevance-based) ---
    for query in queries:
        if inserted >= recent_target:
            break

        video_ids = await search_videos(client, api_key, query, region, language, max_results=15)
        if not video_ids:
            continue

        items = await fetch_video_details(client, api_key, video_ids)

        for item in items:
            if inserted >= recent_target:
                break

            # Ensure the target topic is included
            snippet = item.get("snippet", {})
            topic_details = item.get("topicDetails", {})
            topic_categories = topic_details.get("topicCategories", [])
            category_id = snippet.get("categoryId", "")

            topics = classify_topics(category_id, topic_categories, snippet.get("title", ""), snippet.get("description", ""))
            if topic not in topics:
                topics.append(topic)
                topics.sort()

            if insert_video(db, item, region, dry_run, topic_override=topics):
                inserted += 1

        await asyncio.sleep(0.3)

    # --- Part 2: Older popular videos ---
    if older_target > 0 and queries:
        query = queries[0]
        logger.info("  Fetching older videos for %s/%s (query: %s)", topic, language, query)
        older_items = await search_older_videos(
            client, api_key, query, region, language, max_results=older_target * 3,
        )
        for item in older_items:
            if inserted >= target_count:
                break

            snippet = item.get("snippet", {})
            topic_details = item.get("topicDetails", {})
            topic_categories = topic_details.get("topicCategories", [])
            category_id = snippet.get("categoryId", "")

            topics = classify_topics(category_id, topic_categories, snippet.get("title", ""), snippet.get("description", ""))
            if topic not in topics:
                topics.append(topic)
                topics.sort()

            if insert_video(db, item, region, dry_run, topic_override=topics):
                inserted += 1

    return inserted


async def run_seed(
    languages: list[str],
    topics: list[str],
    videos_per_combo: int,
    dry_run: bool,
):
    settings = get_settings()
    api_key = settings.youtube_api_key
    db = SessionLocal()

    total_combos = len(languages) * len(topics)
    logger.info(
        "Starting seed: %d combos (%d languages x %d topics), target %d videos each",
        total_combos, len(languages), len(topics), videos_per_combo,
    )
    if dry_run:
        logger.info("DRY RUN mode — nothing will be written to the database")

    total_inserted = 0
    combo_num = 0

    try:
        async with httpx.AsyncClient() as client:
            for lang in languages:
                for topic in topics:
                    combo_num += 1
                    logger.info("[%d/%d]  %s / %s", combo_num, total_combos, lang, topic)

                    if topic in CATEGORY_TOPICS:
                        count = await seed_category_topic(
                            client, api_key, db, topic, lang, videos_per_combo, dry_run,
                        )
                    elif topic in SEARCH_TOPICS:
                        count = await seed_search_topic(
                            client, api_key, db, topic, lang, videos_per_combo, dry_run,
                        )
                    else:
                        logger.warning("  No strategy for topic '%s' — skipping", topic)
                        count = 0

                    total_inserted += count
                    logger.info("  → inserted %d videos", count)

                    # Respect API rate limits
                    await asyncio.sleep(0.5)
    except QuotaExhausted:
        logger.warning("API quota exhausted — stopping early. Videos inserted so far: %d", total_inserted)

    db.close()

    # Final summary
    summary_db = SessionLocal()
    total_in_db = summary_db.query(Video).count()
    summary_db.close()

    logger.info("=" * 60)
    logger.info("Seed complete!")
    logger.info("  New videos inserted this run: %d", total_inserted)
    logger.info("  Total videos in database:     %d", total_in_db)
    if dry_run:
        logger.info("  (DRY RUN — nothing was written)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Seed the videos table from YouTube API with auto-classification"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--language", choices=LANGUAGES, help="Seed only this language")
    parser.add_argument("--topic", choices=TOPICS, help="Seed only this topic")
    parser.add_argument(
        "--count", type=int, default=VIDEOS_PER_COMBO,
        help=f"Target videos per topic/language combo (default {VIDEOS_PER_COMBO})",
    )
    args = parser.parse_args()

    langs = [args.language] if args.language else LANGUAGES
    tops = [args.topic] if args.topic else TOPICS

    asyncio.run(run_seed(langs, tops, args.count, args.dry_run))


if __name__ == "__main__":
    main()
