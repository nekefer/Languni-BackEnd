from sqlalchemy import Column, String, Boolean, DateTime, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from ..database.core import Base 

class User(Base):
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)  # Now nullable for Google users
    google_id = Column(String, nullable=True)      # For Google OAuth users
    auth_method = Column(String, nullable=False, default='password')  # 'password' or 'google'
    avatar_url = Column(String, nullable=True)     # Optional profile picture
    is_active = Column(Boolean, default=True)      # Track if user account is active
    
    # Google OAuth tokens for API access
    google_access_token = Column(String, nullable=True)  # Google access token (expires in 1 hour)
    google_refresh_token = Column(String, nullable=True)  # Google refresh token (long-lived)
    google_token_expires_at = Column(DateTime(timezone=True), nullable=True)  # Token expiration timestamp
    
    # User Preferences for Onboarding
    native_language = Column(String(10), nullable=True)  # User's native language (en, fr, es)
    learning_language = Column(String(10), nullable=True)  # Language user wants to learn
    topics = Column(ARRAY(String), nullable=True)  # Topics of interest (music, travel, business)
    level = Column(String(20), nullable=True)  # Learning level (beginner, intermediate, advanced)
    onboarding_completed = Column(Boolean, default=False)  # Whether user completed onboarding
    
    created_at = Column(DateTime, default=datetime.utcnow)  # When user was created
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update time
    
    # Relationships
    user_words = relationship("UserWord", back_populates="user")
    user_videos = relationship("UserVideo", back_populates="user")

    @property
    def saved_words_count(self):
        """Count of words saved by this user"""
        return len(self.user_words)

    def __repr__(self):
        return f"<User(email='{self.email}', first_name='{self.first_name}', last_name='{self.last_name}', auth_method='{self.auth_method}')>"