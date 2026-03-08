from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import get_current_user_from_cookie
from src.auth import models as auth_models
from src.entities.user import User
from src.vocabulary.service import VocabularyService
from src.vocabulary.models import (
    SaveWordRequest, 
    SaveWordResponseSimple, 
    SavedWordsPage,
    SavedWordResponse,
    WordResponse,
    CheckWordResponse,
)
from src.exceptions import ValidationError
from src.rate_limiter import limiter, RATE_LIMITS


router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


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


@router.post("/save", response_model=SaveWordResponseSimple)
@limiter.limit(RATE_LIMITS["vocabulary_save"])
async def save_word(
    request: Request,
    word_data: SaveWordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Save a word to user's vocabulary"""
    try:
        user_word = await VocabularyService.save_word(db, current_user, word_data)
        
        
        # Load the word relationship
        db.refresh(user_word, ["word"])
        
        return SaveWordResponseSimple(
            id=user_word.id,
            word_id=user_word.word_id,
            word=user_word.word.word,
            video_id=user_word.video_id,
            saved_at=user_word.saved_at
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/saved", response_model=SavedWordsPage)
@limiter.limit(RATE_LIMITS["vocabulary_get"])
async def get_saved_words(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user's saved words with pagination."""
    try:
        user_words, total = await VocabularyService.get_user_words(db, current_user, skip, limit)
        
        word_responses = []
        for user_word in user_words:
            word_response = WordResponse(
                id=user_word.word.id,
                word=user_word.word.word,
                created_at=user_word.word.created_at
            )

            saved_word_response = SavedWordResponse(
                id=user_word.id,
                word=word_response,
                video_id=user_word.video_id,
                saved_at=user_word.saved_at,
                translation=user_word.translation,
                native_language=user_word.native_language,
                definition=user_word.definition,
            )
            word_responses.append(saved_word_response)
        
        # Calculate page number from skip and limit for response
        page = (skip // limit) + 1 if limit > 0 else 1
        
        return SavedWordsPage(
            words=word_responses,
            total=total,
            page=page,
            page_size=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch saved words")


@router.get("/check/{word}", response_model=CheckWordResponse)
@limiter.limit(RATE_LIMITS["vocabulary_get"])
async def check_word_saved(
    request: Request,
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if a word is already saved"""
    try:
        user_word = await VocabularyService.is_word_saved(db, current_user, word)
        return CheckWordResponse(
            word=word.lower().strip(),
            saved=user_word is not None,
            definition=user_word.definition if user_word else None,
            translation=user_word.translation if user_word else None,
            native_language=user_word.native_language if user_word else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to check word status")


@router.delete("/{word}")
@limiter.limit(RATE_LIMITS["vocabulary_delete"])
async def delete_saved_word(
    request: Request,
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a saved word"""
    try:
        success = await VocabularyService.delete_word(db, current_user, word)
        if not success:
            raise HTTPException(status_code=404, detail="Word not found in your saved vocabulary")
        
        return {"message": "Word deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete word")

