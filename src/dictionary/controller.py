from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import get_current_user_from_cookie
from src.auth import models as auth_models
from src.entities.user import User
from src.rate_limiter import limiter, RATE_LIMITS
from .models import DictionaryResponse
from .service import DictionaryService, SUPPORTED_LANGUAGES

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])


def get_current_user(
    token_data: auth_models.TokenData = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
) -> User:
    user_id = token_data.get_uuid()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{word}", response_model=DictionaryResponse)
@limiter.limit(RATE_LIMITS.get("dictionary", "30/minute"))
async def get_definition(
    request: Request,
    word: str,
    current_user: User = Depends(get_current_user),
):
    """Fetch word definition from Wiktionary using the user's learning language."""
    language = current_user.learning_language or "en"

    if language not in SUPPORTED_LANGUAGES:
        language = "en"

    result = await DictionaryService.get_definition(word, language)

    if result is None:
        raise HTTPException(status_code=404, detail=f"No definition found for '{word}' in '{language}'")

    return result
