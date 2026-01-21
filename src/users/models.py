from typing import Optional, List
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class UserPreferencesBase(BaseModel):
    """Base model for user learning preferences collected during onboarding."""
    native_language: Optional[str] = Field(None, max_length=10, description="User's native language (en, fr, es)")
    learning_language: Optional[str] = Field(None, max_length=10, description="Language user wants to learn")
    topics: Optional[List[str]] = Field(None, description="Topics of interest (e.g., music, travel, business)")
    level: Optional[str] = Field(None, max_length=20, description="Learning level (beginner, intermediate, advanced)")


class UserPreferencesUpdate(UserPreferencesBase):
    """Payload for saving/updating user preferences."""
    pass


class UserPreferencesResponse(UserPreferencesBase):
    """Response with preferences and onboarding completion status."""
    onboarding_completed: bool = False

    class Config:
        orm_mode = True


class UserResponse(BaseModel):
    """User response including preference fields."""
    id: UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: Optional[str] = None
    is_active: bool = True

    native_language: Optional[str] = None
    learning_language: Optional[str] = None
    topics: Optional[List[str]] = None
    level: Optional[str] = None
    onboarding_completed: bool = False

    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
