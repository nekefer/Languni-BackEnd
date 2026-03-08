from pydantic import BaseModel
from typing import Optional


class PhoneticItem(BaseModel):
    text: Optional[str] = None
    audio: Optional[str] = None


class DefinitionItem(BaseModel):
    definition: str
    example: Optional[str] = None
    synonyms: list[str] = []
    antonyms: list[str] = []


class MeaningItem(BaseModel):
    partOfSpeech: str
    definitions: list[DefinitionItem]
    synonyms: list[str] = []
    antonyms: list[str] = []


class DictionaryResponse(BaseModel):
    word: str
    phonetic: Optional[str] = None
    phonetics: list[PhoneticItem] = []
    audio: Optional[str] = None
    meanings: list[MeaningItem] = []
    globalSynonyms: list[str] = []
    globalAntonyms: list[str] = []
