from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from src.database.core import Base
from datetime import datetime


class Word(Base):
    __tablename__ = "words"
    
    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user_words = relationship("UserWord", back_populates="word")
    
    # @property
    # def popularity_count(self):
    #     """Count of users who saved this word"""
    #     return len(self.user_words)