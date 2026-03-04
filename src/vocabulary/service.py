from sqlalchemy.orm import Session, joinedload, defer
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from src.entities.word import Word
from src.entities.user_word import UserWord
from src.entities.user import User
from src.entities.video import Video
from src.vocabulary.models import SaveWordRequest
from src.exceptions import ValidationError


class VocabularyService:
    
    @staticmethod
    async def save_word(db: Session, user: User, word_data: SaveWordRequest) -> UserWord:
        """Save a word to user's vocabulary"""
        
        clean_word = word_data.word.lower().strip()
        
        # Get or create the word
        word = db.query(Word).filter(Word.word == clean_word).first()
        print(f"Looking for word '{clean_word}': {'found' if word else 'not found'}")
        if not word:
            word = Word(word=clean_word)
            db.add(word)
            db.flush()  # Get the ID without committing
        
        # Check if user already saved this word
        existing = db.query(UserWord).filter(
            UserWord.user_id == user.id,
            UserWord.word_id == word.id
        ).first()
        
        
        if existing:
            raise ValidationError(f"Word '{clean_word}' is already saved")
        
        # Resolve YouTube video ID to internal video FK
        internal_video_id = None
        if word_data.youtube_video_id:
            video = db.query(Video).filter(
                Video.youtube_video_id == word_data.youtube_video_id
            ).first()
            if video:
                internal_video_id = video.id

        # Create user-word relationship
        user_word = UserWord(
            user_id=user.id,
            word_id=word.id,
            video_id=internal_video_id,
            translation=word_data.translation,
            native_language=word_data.native_language,
            definition=word_data.definition,
        )
        
        try:
            db.add(user_word)
            db.commit()
            db.refresh(user_word)
            return user_word
        except IntegrityError:
            db.rollback()
            raise ValidationError("Failed to save word due to database constraint")
    
    @staticmethod
    async def get_user_words(db: Session, user: User, skip: int = 0, limit: int = 100) -> tuple[list[UserWord], int]:
        """Get user's saved words with word details, plus total count for pagination."""
        total = (
            db.query(UserWord)
            .filter(UserWord.user_id == user.id)
            .count()
        )

        items = (
            db.query(UserWord)
            .options(joinedload(UserWord.word).defer(Word.created_at))
            .filter(UserWord.user_id == user.id)
            .order_by(UserWord.saved_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        print(f"Retrieved {len(items)} words for user {user.id} (total: {total})")
        return items, total
    
    @staticmethod
    async def is_word_saved(db: Session, user: User, word_text: str) -> UserWord | None:
        """Check if user has saved a word. Returns the UserWord row or None."""
        clean_word = word_text.lower().strip()

        return db.query(UserWord).join(Word).filter(
            UserWord.user_id == user.id,
            Word.word == clean_word
        ).first()
    
    @staticmethod
    async def delete_word(db: Session, user: User, word_text: str) -> bool:
        """Delete a user's saved word"""
        clean_word = word_text.lower().strip()
        
        # Find the user_word entry
        user_word = db.query(UserWord).join(Word).filter(
            UserWord.user_id == user.id,
            Word.word == clean_word
        ).first()
        
        if not user_word:
            return False
        
        db.delete(user_word)
        db.commit()
        return True
    
    
    @staticmethod
    async def get_word_by_text(db: Session, word_text: str) -> Word:
        """Get word by text, return None if not found"""
        clean_word = word_text.lower().strip()
        return db.query(Word).filter(Word.word == clean_word).first()