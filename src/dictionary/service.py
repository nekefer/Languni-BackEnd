import re
import logging
import httpx
from bs4 import BeautifulSoup, Tag
from cachetools import TTLCache
from src.dictionary.models import DictionaryResponse, MeaningItem, DefinitionItem

logger = logging.getLogger("dictionary.service")

# 24-hour cache
_DICT_CACHE: TTLCache = TTLCache(maxsize=2048, ttl=86400)

SUPPORTED_LANGUAGES = {"en", "es", "fr", "de", "it", "pt"}

# For English: use the REST API and filter by 'en' key.
# For other languages: call that language's Wiktionary and find the native section.
LANG_CONFIG = {
    "en": {"use_rest": True},
    "es": {"wiki": "es", "native_name": "Español"},
    "fr": {"wiki": "fr", "native_name": "Français"},
    "de": {"wiki": "de", "native_name": "Deutsch"},
    "it": {"wiki": "it", "native_name": "Italiano"},
    "pt": {"wiki": "pt", "native_name": "Português"},
}

_USER_AGENT = (
    "Linguini/1.0 (https://github.com/linguini; contact@linguini.app) httpx/0.25"
)
_REST_HEADERS = {"User-Agent": _USER_AGENT, "Accept": "application/json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    # Remove <style> blocks entirely (content + tag)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return _fix_encoding(clean)


def _fix_encoding(text: str) -> str:
    """Fix Wiktionary's occasional double-encoded UTF-8."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _is_lang_section(tag: Tag) -> bool:
    """Matches <div class="mw-heading mw-heading2"> (language-level section)."""
    return tag.name == "div" and "mw-heading2" in tag.get("class", [])


def _is_pos_section(tag: Tag) -> bool:
    """Matches <div class="mw-heading mw-heading3|4|5"> (part-of-speech level)."""
    classes = tag.get("class", [])
    return tag.name == "div" and any(c in classes for c in ("mw-heading3", "mw-heading4", "mw-heading5"))


def _section_text(tag: Tag) -> str:
    """Get readable text from a mw-heading div, excluding edit links."""
    clone = BeautifulSoup(str(tag), "html.parser").find()
    for edit in clone.find_all("span", class_="mw-editsection"):
        edit.decompose()
    return clone.get_text(strip=True)


# ---------------------------------------------------------------------------
# English — REST API
# ---------------------------------------------------------------------------

async def _fetch_english(word: str) -> DictionaryResponse | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://en.wiktionary.org/api/rest_v1/page/definition/{word}",
                headers=_REST_HEADERS,
                timeout=8.0,
            )
    except Exception as e:
        logger.error(f"REST request failed for '{word}': {e}")
        return None

    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        logger.error(f"REST API {resp.status_code} for '{word}'")
        return None

    data = resp.json()
    entries = data.get("en")
    if not entries:
        return None

    meanings = []
    for entry in entries:
        defs = []
        for raw in entry.get("definitions", []):
            text = _strip_html(raw.get("definition", ""))
            if not text:
                continue
            parsed = raw.get("parsedExamples", [])
            example = _strip_html(parsed[0].get("example", "")) if parsed else None
            defs.append(DefinitionItem(definition=text, example=example or None))
        if defs:
            meanings.append(MeaningItem(
                partOfSpeech=entry.get("partOfSpeech", ""),
                definitions=defs,
            ))

    return DictionaryResponse(word=word, meanings=meanings) if meanings else None


# ---------------------------------------------------------------------------
# Non-English — MediaWiki HTML parse API
# ---------------------------------------------------------------------------

async def _fetch_native(word: str, language: str) -> DictionaryResponse | None:
    wiki = LANG_CONFIG[language]["wiki"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{wiki}.wiktionary.org/w/api.php",
                params={"action": "parse", "page": word, "prop": "text", "format": "json"},
                headers={"User-Agent": _USER_AGENT},
                timeout=10.0,
                follow_redirects=True,
            )
    except Exception as e:
        logger.error(f"MediaWiki request failed for '{word}' ({language}): {e}")
        return None

    if resp.status_code != 200:
        logger.error(f"MediaWiki {resp.status_code} for '{word}' ({language})")
        return None

    data = resp.json()
    if "error" in data:
        logger.info(f"MediaWiki error for '{word}' ({language}): {data['error']}")
        return None

    html = data.get("parse", {}).get("text", {}).get("*", "")
    if not html:
        return None

    return _parse_mediawiki_html(word, html, language)


def _parse_mediawiki_html(word: str, html: str, language: str) -> DictionaryResponse | None:
    soup = BeautifulSoup(html, "html.parser")
    output_div = soup.find("div", class_="mw-parser-output")
    if not output_div:
        return None

    # Strategy 1: find via <span class="headline-lang" id="{language}"> (es.wiktionary)
    lang_span = output_div.find("span", class_="headline-lang", id=language)
    target_lang_div = lang_span.find_parent("div", class_="mw-heading2") if lang_span else None

    # Strategy 2: find by native language name in text (fr.wiktionary and others)
    if not target_lang_div:
        native_name = LANG_CONFIG.get(language, {}).get("native_name", "")
        if native_name:
            for div in output_div.find_all("div", class_="mw-heading2"):
                if native_name in div.get_text():
                    target_lang_div = div
                    break

    if not target_lang_div:
        logger.info(f"Language section '{language}' not found for '{word}'")
        return None

    # Walk ALL siblings of mw-parser-output after the language div
    in_section = False
    meanings: list[MeaningItem] = []
    current_pos = ""
    current_defs: list[DefinitionItem] = []

    def flush():
        if current_pos and current_defs:
            meanings.append(MeaningItem(partOfSpeech=current_pos, definitions=list(current_defs)))

    for tag in output_div.children:
        if not hasattr(tag, "name") or not tag.name:
            continue

        if tag == target_lang_div:
            in_section = True
            continue

        if not in_section:
            continue

        # Stop at the next language-level section
        if _is_lang_section(tag):
            break

        if _is_pos_section(tag):
            pos_text = _section_text(tag)
            # Skip non-definition sections (etymology, references, see-also, etc.)
            skip_words = (
                "étymol", "etimol", "etymol", "referenc", "véase", "voir",
                "also", "note", "pronunc", "transcr", "transliter",
            )
            if any(w in pos_text.lower() for w in skip_words):
                flush()
                current_defs = []
                current_pos = ""
                continue
            flush()
            current_defs = []
            current_pos = pos_text
        elif tag.name == "dl":
            for dd in tag.find_all("dd", recursive=False):
                text = _strip_html(str(dd))
                if text:
                    current_defs.append(DefinitionItem(definition=text))
        elif tag.name == "ol":
            for li in tag.find_all("li", recursive=False):
                text = _strip_html(str(li))
                if text:
                    current_defs.append(DefinitionItem(definition=text))

    flush()

    return DictionaryResponse(word=word, meanings=meanings) if meanings else None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class DictionaryService:

    @staticmethod
    async def get_definition(word: str, language: str = "en") -> DictionaryResponse | None:
        clean = word.lower().strip()
        cache_key = (clean, language)

        if cache_key in _DICT_CACHE:
            logger.debug(f"Cache hit: '{clean}' ({language})")
            return _DICT_CACHE[cache_key]

        if language == "en":
            result = await _fetch_english(clean)
        else:
            result = await _fetch_native(clean, language)

        _DICT_CACHE[cache_key] = result
        return result
