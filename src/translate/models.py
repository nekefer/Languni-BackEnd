from pydantic import BaseModel
from typing import Optional


class TranslateRequest(BaseModel):
    text: str  # supports single words and multi-word phrases
    context: Optional[str] = None  # surrounding sentence for context-aware translation


class TranslateResponse(BaseModel):
    translatedWord: str
    sourceLanguage: str
    targetLanguage: str
