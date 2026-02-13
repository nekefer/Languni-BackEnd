import logging
from cachetools import TTLCache
from deep_translator import GoogleTranslator
from fastapi import HTTPException

logger = logging.getLogger("translate.service")

# 1-hour server-side cache
_TRANSLATION_CACHE = TTLCache(maxsize=1024, ttl=3600)


class TranslationService:
    @staticmethod
    def translate_word(word: str, source_language: str, target_language: str) -> str:
     
        cache_key = (word.lower().strip(), source_language, target_language)

        if cache_key in _TRANSLATION_CACHE:
            logger.debug(f"Cache hit for '{word}' ({source_language} -> {target_language})")
            return _TRANSLATION_CACHE[cache_key]

        try:
            translator = GoogleTranslator(source=source_language, target=target_language)
            translated = translator.translate(word.strip())

            if not translated:
                raise HTTPException(status_code=502, detail="No translation returned from Google Translate")

            _TRANSLATION_CACHE[cache_key] = translated
            logger.info(f"Translated '{word}' ({source_language} -> {target_language}): '{translated}'")
            return translated

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Translation failed for '{word}' ({source_language} -> {target_language}): {e}")
            raise HTTPException(status_code=502, detail=f"Translation service error: {str(e)}")
