from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.database.core import get_db
from src.auth.service import CurrentUser, change_password as auth_change_password
from src.auth.models import PasswordChange
from src.exceptions import AuthenticationError
from src.entities.user import User
from src.entities.user_word import UserWord
from src.entities.user_video import UserVideo
from src.entities.subscription import Subscription
from src.users.models import (
	UserPreferencesUpdate,
	UserPreferencesResponse,
	UserProfileUpdate,
	UserProfileResponse,
)
from src.config import get_settings

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


@router.patch("/profile", response_model=UserProfileResponse)
async def update_profile(
	profile: UserProfileUpdate,
	token: CurrentUser,
	db: Session = Depends(get_db),
):
	"""Update user first_name and last_name."""
	user = db.query(User).filter(User.id == token.get_uuid()).first()
	if not user:
		raise HTTPException(status_code=401, detail="User not found")
	user.first_name = profile.first_name
	user.last_name = profile.last_name
	db.commit()
	db.refresh(user)
	return UserProfileResponse(first_name=user.first_name, last_name=user.last_name, email=user.email)


@router.post("/change-password", status_code=204)
async def change_password_endpoint(
	payload: PasswordChange,
	token: CurrentUser,
	db: Session = Depends(get_db),
):
	"""Change password for email/password users. Not available for Google-only accounts."""
	user = db.query(User).filter(User.id == token.get_uuid()).first()
	if not user:
		raise HTTPException(status_code=401, detail="User not found")
	if user.auth_method == 'google':
		raise HTTPException(status_code=400, detail="Password change not available for Google-only accounts")
	try:
		auth_change_password(db, user.id, payload)
	except AuthenticationError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.delete("", status_code=200)
async def delete_account(
	token: CurrentUser,
	db: Session = Depends(get_db),
	settings=Depends(get_settings),
):
	"""Delete account and all associated data, then clear auth cookies."""
	user = db.query(User).filter(User.id == token.get_uuid()).first()
	if not user:
		raise HTTPException(status_code=401, detail="User not found")

	user_id = user.id
	db.query(Subscription).filter(Subscription.user_id == user_id).delete()
	db.query(UserWord).filter(UserWord.user_id == user_id).delete()
	db.query(UserVideo).filter(UserVideo.user_id == user_id).delete()
	db.delete(user)
	db.commit()

	response = JSONResponse(content={"message": "Account deleted"})
	for cookie in ("access_token", "refresh_token", "user_email", "user_type"):
		response.delete_cookie(key=cookie, path="/", secure=settings.is_production, httponly=True, samesite="lax")
	return response
