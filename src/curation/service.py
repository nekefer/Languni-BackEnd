"""Reuse seed discovery and transcript conversion, adding an explicit review stage."""
import asyncio
from datetime import datetime, timezone
import time

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from scripts.seed_videos import (
    CATEGORY_SEARCH_QUERIES, SEARCH_TOPICS, LANG_TO_REGION,
    classify_topics, fetch_video_details, parse_iso8601_duration, search_videos,
)
from .schema import Batch, Caption, Lesson, digest


def now():
    return datetime.now(timezone.utc).isoformat()


def candidate(item, language, topic):
    snippet = item["snippet"]
    duration = parse_iso8601_duration(item.get("contentDetails", {}).get("duration", ""))
    status = item.get("status", {})
    declared = (snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or "").split("-")[0].lower()
    if status.get("embeddable") is False or status.get("privacyStatus") != "public":
        return None
    if not 60 <= duration <= 1800 or snippet.get("liveBroadcastContent", "none") != "none":
        return None
    if declared and declared != language:
        return None
    topics = classify_topics(snippet.get("categoryId", ""), item.get("topicDetails", {}).get("topicCategories", []), snippet["title"], snippet.get("description", ""))
    return {
        "youtube_video_id": item["id"], "title": snippet["title"],
        "channel_title": snippet.get("channelTitle", ""),
        "youtube_published_at": snippet["publishedAt"], "language": language,
        "topics": sorted(set(topics + [topic])), "difficulty_level": "intermediate",
        "duration_seconds": duration, "state": "suggested", "notes": "",
        "reason": f"{topic.title()} candidate, {duration // 60} min. " + ("Language from YouTube metadata." if declared else "Language needs confirmation in preview."),
        "warnings": [], "error": None, "discovered_at": now(),
    }


async def discover(store, api_key, languages, topics, count=5, refresh=False, query=None):
    added = 0
    async with httpx.AsyncClient() as client:
        for language in languages:
            for topic in topics:
                queries = (SEARCH_TOPICS.get(topic) or CATEGORY_SEARCH_QUERIES[topic])[language]
                # Gaming remains compatible with the existing Entertainment preference.
                search_query = query or queries[0]
                key = digest([language, topic, search_query, count])
                cached = store.cached_search(key)
                if cached and not refresh and time.time() - cached["time"] < 86400:
                    items = cached["items"]
                else:
                    ids = await search_videos(client, api_key, search_query, LANG_TO_REGION[language], language, min(50, count * 3))
                    items = await fetch_video_details(client, api_key, ids)
                    store.save_search(key, {"time": time.time(), "items": items})
                accepted = 0
                existing = {row["youtube_video_id"] for row in store.all()}
                for item in items:
                    row = candidate(item, language, topic)
                    if row is None or row["youtube_video_id"] in existing:
                        continue
                    store.save(row, new=True)
                    existing.add(row["youtube_video_id"])
                    added += 1
                    accepted += 1
                    if accepted == count:
                        break
                await asyncio.sleep(0.2)
    return {"added": added}


def prepare(store, video_id):
    row = store.get(video_id)
    if row["state"] not in ("approved", "failed"):
        raise ValueError("Approve the candidate before downloading subtitles")
    row.update(state="downloading", error=None)
    store.save(row)
    try:
        tracks = list(YouTubeTranscriptApi().list(video_id))
        matches = [t for t in tracks if t.language_code.split("-")[0].lower() == row["language"]]
        if not matches:
            raise ValueError("No subtitle track in the approved language. Choose another video or correct its language.")
        track = sorted(matches, key=lambda t: t.is_generated)[0]
        captions = [Caption(text=c.text.strip(), start=c.start, duration=c.duration).model_dump() for c in track.fetch() if c.text.strip()]
        row.update(subtitles=captions, subtitle_language=row["language"],
                   subtitle_source="youtube_generated" if track.is_generated else "youtube_manual",
                   subtitle_fetched_at=now(), subtitle_checksum=digest(captions))
        # Structural checks are mandatory; quality flags are reviewed by the editor.
        lesson(row)
        warnings = []
        if track.is_generated:
            warnings.append("Automatically generated captions: check spelling and timing.")
        if len(captions) < 10 or captions[-1]["start"] < row["duration_seconds"] * 0.7:
            warnings.append("Transcript may be incomplete. Check the end of the video.")
        if any(b["start"] - (a["start"] + a["duration"]) > 45 for a, b in zip(captions, captions[1:])):
            warnings.append("Transcript has gaps longer than 45 seconds. Check for missing speech.")
        row.update(state="needs_review", warnings=warnings)
    except Exception as exc:
        # Do not retain upstream exception text containing request URLs or cookies.
        row.update(state="failed", error=str(exc) if isinstance(exc, ValueError) and not hasattr(exc, "video_id") else f"Subtitle download failed ({type(exc).__name__}). Retry locally or choose another video.")
    store.save(row)
    return row


def lesson(row):
    return Lesson.model_validate({key: row[key] for key in Lesson.model_fields if key != "reviewed"} | {"reviewed": True})


def make_batch(store, ids):
    rows = [store.get(video_id) for video_id in ids]
    if not rows or any(row["state"] not in ("ready", "published") for row in rows):
        raise ValueError("Select only reviewed, ready videos")
    return Batch(lessons=[lesson(row) for row in rows])
