from pydantic import BaseModel


class TranslateRequest(BaseModel):
    word: str

class TranslateResponse(BaseModel):
    translatedWord: str
    sourceLanguage: str
    targetLanguage: str
