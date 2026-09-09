"""Shared validation for local review and production imports; no database imports."""
import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["en", "fr", "es"]
Level = Literal["beginner", "intermediate", "advanced"]
TOPICS = ("music", "travel", "food", "sports", "technology", "business", "entertainment", "science", "culture", "news", "education", "lifestyle")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class Caption(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=10000)
    start: float = Field(ge=0)
    duration: float = Field(gt=0)


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    youtube_video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(min_length=1, max_length=500)
    channel_title: str = Field(max_length=500)
    youtube_published_at: datetime
    language: Language
    topics: list[str] = Field(min_length=1, max_length=12)
    difficulty_level: Level
    duration_seconds: int = Field(gt=0, le=7200)
    subtitle_language: Language
    subtitle_source: Literal["youtube_manual", "youtube_generated"]
    subtitle_fetched_at: datetime
    subtitles: list[Caption] = Field(min_length=2, max_length=30000)
    subtitle_checksum: str
    reviewed: Literal[True]

    @model_validator(mode="after")
    def validate_lesson(self):
        if self.language != self.subtitle_language:
            raise ValueError("Subtitle language must match the lesson language")
        if any(topic not in TOPICS for topic in self.topics) or len(set(self.topics)) != len(self.topics):
            raise ValueError("Unknown or duplicate interest")
        previous = -1.0
        for caption in self.subtitles:
            if not caption.text.strip() or caption.start < previous:
                raise ValueError("Subtitle text must be nonempty and timestamps ordered")
            if caption.start + caption.duration > self.duration_seconds + 10:
                raise ValueError("Subtitles extend beyond the video duration")
            previous = caption.start
        if digest([c.model_dump() for c in self.subtitles]) != self.subtitle_checksum:
            raise ValueError("Subtitle checksum does not match")
        return self


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    lessons: list[Lesson] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [lesson.youtube_video_id for lesson in self.lessons]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate video IDs in publication batch")
        return self
