"""One transaction, stable IDs, explicit target and preview-bound publishing."""
from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import make_url

from .schema import Batch, digest


def target_label(url):
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Publication requires an explicit PostgreSQL destination")
    if not parsed.host or parsed.host.endswith(".railway.internal"):
        raise ValueError("Use Railway's external database connection or a local Railway tunnel")
    return f"{parsed.host}:{parsed.port or 5432}/{parsed.database}"


def values_for(lesson):
    return {
        "youtube_video_id": lesson.youtube_video_id, "title": lesson.title,
        "url": f"https://www.youtube.com/watch?v={lesson.youtube_video_id}",
        "thumbnail_url": f"https://i.ytimg.com/vi/{lesson.youtube_video_id}/hqdefault.jpg",
        "channel_title": lesson.channel_title,
        "youtube_published_at": lesson.youtube_published_at.isoformat(),
        "language": lesson.language, "topics": lesson.topics,
        "difficulty_level": lesson.difficulty_level,
        "video_type": "short" if lesson.duration_seconds <= 60 else "video",
        "subtitles": [caption.model_dump() for caption in lesson.subtitles],
        "subtitle_language": lesson.subtitle_language,
        "subtitle_fetched_at": lesson.subtitle_fetched_at,
        "subtitle_checksum": lesson.subtitle_checksum, "publication_status": "published",
    }


def comparable(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    return value


def publish_batch(engine, batch: Batch, target, expected_preview=None):
    """Omitting expected_preview is strictly read-only. A changed plan cannot publish."""
    with engine.begin() as conn:
        if expected_preview and conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(73481629)"))
        videos = Table("videos", MetaData(), autoload_with=conn)
        needed = set(values_for(batch.lessons[0]))
        if not needed.issubset(videos.c.keys()):
            raise ValueError("Destination schema is outdated. Run the reviewed Alembic migration first.")
        changes = []
        writes = []
        for lesson in batch.lessons:
            values = values_for(lesson)
            query = select(videos).where(videos.c.youtube_video_id == lesson.youtube_video_id)
            if expected_preview:
                query = query.with_for_update()
            old = conn.execute(query).mappings().first()
            fields = [key for key, value in values.items() if old is None or comparable(old[key]) != comparable(value)]
            changes.append({
                "video_id": lesson.youtube_video_id, "title": lesson.title,
                "action": "insert" if old is None else "update" if fields else "unchanged",
                "fields": fields, "caption_count": len(lesson.subtitles),
                "previous_checksum": old["subtitle_checksum"] if old else None,
                "previous_record": digest({key: comparable(old[key]) for key in values}) if old else None,
            })
            writes.append((old["id"] if old else None, values, fields))
        preview = {"target": target, "batch_checksum": digest(batch.model_dump(mode="json")), "changes": changes}
        preview["preview_id"] = digest(preview)
        if expected_preview:
            if expected_preview != preview["preview_id"]:
                raise ValueError("The batch or destination changed. Preview again before publishing.")
            for existing_id, values, fields in writes:
                if existing_id is None:
                    conn.execute(videos.insert().values(**values))
                elif fields:
                    conn.execute(videos.update().where(videos.c.id == existing_id).values(**values, updated_at=datetime.now(timezone.utc)))
        preview["published"] = bool(expected_preview)
        return preview
