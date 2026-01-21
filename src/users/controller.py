from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.database.core import get_db
from src.auth.service import CurrentUser
from src.entities.user import User
from src.users.models import (
	UserPreferencesUpdate,
	UserPreferencesResponse,
)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
	token: CurrentUser,
	db: Session = Depends(get_db),
):
	"""Return current user's learning preferences."""
	user = db.query(User).filter(User.id == token.get_uuid()).first()
	if not user:
		raise HTTPException(status_code=401, detail="User not found")
	return UserPreferencesResponse(
		native_language=user.native_language,
		learning_language=user.learning_language,
		topics=user.topics or [],
		level=user.level,
		onboarding_completed=bool(user.onboarding_completed),
	)


@router.post("/preferences", response_model=UserPreferencesResponse)
async def save_user_preferences(
	preferences: UserPreferencesUpdate,
	token: CurrentUser,
	db: Session = Depends(get_db),
):
	"""Save or update user preferences (marks onboarding as completed)."""
	user = db.query(User).filter(User.id == token.get_uuid()).first()
	if not user:
		raise HTTPException(status_code=401, detail="User not found")
	user.native_language = preferences.native_language
	user.learning_language = preferences.learning_language
	user.topics = preferences.topics
	user.level = preferences.level
	user.onboarding_completed = True

	db.commit()
	db.refresh(user)

	return UserPreferencesResponse(
		native_language=user.native_language,
		learning_language=user.learning_language,
		topics=user.topics or [],
		level=user.level,
		onboarding_completed=True,
	)


@router.put("/preferences", response_model=UserPreferencesResponse)
async def update_user_preferences(
	preferences: UserPreferencesUpdate,
	token: CurrentUser,
	db: Session = Depends(get_db),
):
	"""Update existing preferences via settings page."""
	return await save_user_preferences(preferences, token, db)

