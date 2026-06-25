from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import get_current_user_from_cookie
from src.auth import models as auth_models
from src.entities.user import User
from src.rate_limiter import limiter, RATE_LIMITS
from src.config import get_settings, Settings
from src.exceptions import AuthenticationError
from .models import TranslateRequest, TranslateResponse
from .service import TranslationService


router = APIRouter(prefix="/api/translate", tags=["translation"])


def get_current_user(
    token_data: auth_models.TokenData = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
) -> User:
    """Convert token data to User object"""
    user_id = token_data.get_uuid()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    try:
        token_data = get_current_user_from_cookie(request, settings)
    except AuthenticationError:
        return None

    user_id = token_data.get_uuid()
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


@router.post("", response_model=TranslateResponse)
@limiter.limit(RATE_LIMITS["translate"])
async def translate_word(
    request: Request,
    body: TranslateRequest,
    current_user: User | None = Depends(get_optional_user),
):
    """Translate a word using profile preferences or explicit guest languages."""
    source = current_user.learning_language if current_user else body.sourceLanguage
    target = current_user.native_language if current_user else body.targetLanguage

    if not source or not target:
        raise HTTPException(
            status_code=400,
            detail="Language preferences not set.",
        )

    translated = TranslationService.translate_word(
        body.text,
        source,
        target,
    )

    return TranslateResponse(
        translatedWord=translated,
        sourceLanguage=source,
        targetLanguage=target,
    )
