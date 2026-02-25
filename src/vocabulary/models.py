from pydantic import BaseModel, validator
from datetime import datetime
from typing import Optional


class SaveWordRequest(BaseModel):
    word: str
    video_id: Optional[int] = None
    translation: Optional[str] = None       # translated word in user's native language
    native_language: Optional[str] = None   # user's native language code (en, fr, es)
    definition: Optional[str] = None        # JSON-serialized definition snapshot

    @validator('word')
    def validate_word(cls, v):
        if not v or not v.strip():
            raise ValueError('Word cannot be empty')
        return v.lower().strip()


class WordResponse(BaseModel):
    id: int
    word: str
    created_at: datetime

    class Config:
        from_attributes = True


class SavedWordResponse(BaseModel):
    id: int
    word: WordResponse  # Nested word details
    video_id: Optional[int]
    saved_at: datetime
    translation: Optional[str] = None
    native_language: Optional[str] = None
    definition: Optional[str] = None

    class Config:
        from_attributes = True



class SavedWordsPage(BaseModel):
    words: list[SavedWordResponse]
    total: int
    page: int
    page_size: int


class CheckWordResponse(BaseModel):
    word: str
    saved: bool
    definition: Optional[str] = None
    translation: Optional[str] = None
    native_language: Optional[str] = None



class SaveWordResponseSimple(BaseModel):
    id: int
    word_id: int
    word: str
    video_id: Optional[int]
    saved_at: datetime
    message: str = "Word saved successfully"