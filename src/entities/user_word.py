from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from src.database.core import Base
from datetime import datetime


class UserWord(Base):
    __tablename__ = "user_words"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    word_id = Column(Integer, ForeignKey("words.id"), nullable=False)
    video_id = Column(String(255), nullable=True)  # Where they found the word
    saved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Translation in user's native language
    translation = Column(String, nullable=True)  # Word translation in user's native language
    native_language = Column(String(10), nullable=True)  # Target language for translation (en, fr, es)
    
    # Relationships
    user = relationship("User", back_populates="user_words")
    word = relationship("Word", back_populates="user_words")
    
    # Ensure user can't save same word twice
    __table_args__ = (
        UniqueConstraint('user_id', 'word_id', name='unique_user_word'),
    )