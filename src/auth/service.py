from datetime import timedelta, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4
import hashlib
import secrets
from fastapi import Depends, Request, HTTPException
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError
from sqlalchemy.orm import Session
from src.entities.user import User
from . import models
from fastapi.security import OAuth2PasswordRequestForm
from ..exceptions import AuthenticationError
from ..config import get_settings, Settings
from ..database.core import DbSession
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from src.security.crypto import encrypt_token, decrypt_token

bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
logger = logging.getLogger("auth.google")


def refresh_google_token(db: Session, user_id: UUID, settings: Settings) -> str:
    """
    Refresh expired Google access token using refresh token.
    
    Args:
        db: Database session
        user_id: User UUID
        settings: Application settings
        
    Returns:
        New access token
        
    Raises:
        AuthenticationError: If refresh fails
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.google_refresh_token:
        logger.error(f"No Google refresh token for user {user_id}")
        raise AuthenticationError("No Google refresh token available. Please reconnect your Google account.")
    
    try:
        # Create credentials object
        credentials = Credentials(
            token=decrypt_token(user.google_access_token),
            refresh_token=decrypt_token(user.google_refresh_token),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret
        )
        
        # Refresh the token
        credentials.refresh(GoogleRequest())
        
        # Update database with new tokens (store encrypted)
        user.google_access_token = encrypt_token(credentials.token)
        user.google_token_expires_at = credentials.expiry
        
        # Google may issue a new refresh token
        if credentials.refresh_token:
            user.google_refresh_token = encrypt_token(credentials.refresh_token)
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"Successfully refreshed Google token for user {user_id}")
        return credentials.token  # return plaintext for immediate use
        
    except Exception as e:
        logger.error(f"Failed to refresh Google token for user {user_id}: {str(e)}")
        db.rollback()
        raise AuthenticationError("Failed to refresh Google token. Please reconnect your Google account.")


def get_valid_google_token(db: Session, user_id: UUID, settings: Settings) -> str:
    """
    Get a valid Google access token, refreshing if necessary.
    
    Args:
        db: Database session
        user_id: User UUID
        settings: Application settings
        
    Returns:
        Valid access token
        
    Raises:
        AuthenticationError: If user not found or token refresh fails
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthenticationError("User not found")
    
    if not user.google_access_token:
        raise AuthenticationError("No Google account connected. Please sign in with Google.")
    
    # Check if token is expired or about to expire (within 5 minutes)
    now = datetime.now(timezone.utc)
    needs_refresh = (
        not user.google_token_expires_at or 
        user.google_token_expires_at <= now + timedelta(minutes=5)
    )
    
    if needs_refresh:
        logger.info(f"Token expired or expiring soon for user {user_id}, refreshing...")
        return refresh_google_token(db, user_id, settings)
    
    logger.debug(f"Using existing token for user {user_id} (expires at {user.google_token_expires_at})")
    return decrypt_token(user.google_access_token)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return bcrypt_context.hash(password)


def authenticate_user(email: str, password: str, db: Session) -> User | bool:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        logging.warning(f"Failed authentication attempt for email")
        return False
    
    # Only allow password login if auth_method is 'password' or 'both'
    if user.auth_method not in ('password', 'both'):
        return False
    
    # Check if user has a password hash and verify it
    if not user.password_hash or not verify_password(password, user.password_hash):
        logging.warning(f"Failed authentication attempt for email")
        return False
    
    logging.info(f"Successful password authentication for user")
    return user


def create_access_token(email: str, user_id: UUID, expires_delta: timedelta, secret_key: str, algorithm: str) -> str:
    """Create a short-lived access token for API calls."""
    encode = {
        'sub': email,
        'id': str(user_id),
        'type': 'access',  # ✅ Added type for clarity
        'exp': datetime.now(timezone.utc) + expires_delta,
        'iat': datetime.now(timezone.utc)  # Issued at
    }
    return jwt.encode(encode, secret_key, algorithm=algorithm)


def create_refresh_token(user_id: UUID, expires_delta: timedelta, secret_key: str, algorithm: str) -> str:
    """✅ NEW: Create a stateless refresh token (no database storage)."""
    encode = {
        'sub': str(user_id),        # User ID
        'type': 'refresh',          # Token type (prevents using access tokens as refresh tokens)
        'exp': datetime.now(timezone.utc) + expires_delta,  # Expiration time
        'jti': str(uuid4()),        # JWT ID - unique identifier for this token
        'iat': datetime.now(timezone.utc)  # Issued at timestamp
    }
    return jwt.encode(encode, secret_key, algorithm=algorithm)


# ✅ REMOVED: All database-dependent functions
# - hash_token()
# - store_refresh_token()
# - revoke_refresh_token()


def verify_refresh_token(token: str, secret_key: str, algorithm: str) -> models.TokenData:
    """✅ NEW: Verify refresh token without database lookup (stateless)."""
    try:
        # Decode and verify the JWT signature
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        
        # Check if it's actually a refresh token
        if payload.get('type') != 'refresh':
            raise AuthenticationError("Invalid token type")
        
        # Extract user ID
        user_id = payload.get('sub')
        if not user_id:
            raise AuthenticationError("Invalid refresh token")
        
        # Return the user data
        return models.TokenData(user_id=user_id, token_type="refresh")
        
    except PyJWTError as e:
        # JWT is invalid (expired, wrong signature, etc.)
        logging.warning(f"Refresh token verification failed: {str(e)}")
        raise AuthenticationError("Invalid refresh token")


def create_token_pair(user: User, settings: Settings, db: Session) -> models.Token:
    """
    ✅ UPDATED: Create both access and refresh tokens (stateless refresh tokens).
    
    Access token: Short-lived (30 minutes) for API calls
    Refresh token: Long-lived (7 days) for getting new access tokens
    """
    # Create access token (short-lived)
    access_token = create_access_token(
        user.email, 
        user.id, 
        timedelta(minutes=settings.access_token_expire_minutes),
        settings.jwt_secret_key, 
        settings.algorithm
    )
    # Create refresh token (long-lived)
    refresh_expires = timedelta(days=settings.refresh_token_expire_days)
    refresh_token = create_refresh_token(
        user.id,
        refresh_expires,
        settings.jwt_secret_key,
        settings.algorithm
    )

    # Store hash — invalidates any previous refresh token for this user
    user.refresh_token_hash = _hash_token(refresh_token)
    db.commit()

    return models.Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60
    )


def verify_token(token: str, secret_key: str, algorithm: str) -> models.TokenData:
    """Verify access token (stateless)."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        
        # ✅ Added type validation for access tokens
        if payload.get('type') != 'access':
            raise AuthenticationError("Invalid token type")
        
        user_id: str = payload.get('id')
        if not user_id:
            raise AuthenticationError("Invalid token")
            
        return models.TokenData(user_id=user_id)
    except PyJWTError as e:
        logging.warning(f"Token verification failed: {str(e)}")
        raise AuthenticationError("Invalid token")


def register_user(db: Session, register_user_request: models.RegisterUserRequest) -> None:
    "check if the user already exists, if raise an error, otherwise create a new user"
    existing_user = db.query(User).filter(User.email == register_user_request.email).first()
    if existing_user:
        raise AuthenticationError("A user with this email already exists.")
    try:
        create_user_model = User(
            id=uuid4(),
            email=register_user_request.email,
            first_name=register_user_request.first_name,
            last_name=register_user_request.last_name,
            password_hash=get_password_hash(register_user_request.password)
        )    
        db.add(create_user_model)
        db.commit()
    except Exception as e:
        db.rollback()  # Rollback on error to prevent partial data
        logging.error(f"Failed to register user: {register_user_request.email}. Error: {str(e)}")
        raise AuthenticationError(f"Registration failed: {str(e)}")


def get_current_user_from_cookie(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> models.TokenData:
    """Get current user from HttpOnly cookie instead of Authorization header."""
    token = request.cookies.get("access_token")
    if not token:
        raise AuthenticationError("No access token found in cookies")
    
    return verify_token(token, settings.jwt_secret_key, settings.algorithm)

# Cookie-based authentication for all endpoints
CurrentUser = Annotated[models.TokenData, Depends(get_current_user_from_cookie)]


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_verification_token(db: Session, user: User) -> str:
    """Generate a verification token, store its hash in DB, return the raw token."""
    from sqlalchemy import text
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # Use a raw UPDATE to bypass any ORM tracking issues
    db.execute(
        text("UPDATE users SET verification_token = :token, verification_token_expires_at = :expires WHERE id = :uid"),
        {"token": token_hash, "expires": expires_at, "uid": str(user.id)},
    )
    db.commit()

    # Confirm the write landed
    result = db.execute(
        text("SELECT verification_token FROM users WHERE id = :uid"),
        {"uid": str(user.id)},
    ).fetchone()
    stored = result[0] if result else None
    logging.info(f"[verify-token] stored hash prefix for {user.email}: {stored[:8] if stored else 'NONE'}")
    logging.info(f"[verify-token] expected hash prefix: {token_hash[:8]}")

    return raw_token


def verify_email_token(db: Session, raw_token: str) -> User:
    """Verify the email token. Marks the user as verified on success."""
    token_hash = _hash_token(raw_token)
    logging.info(f"[verify-email] looking up hash prefix: {token_hash[:8]}")
    user = db.query(User).filter(User.verification_token == token_hash).first()
    if not user:
        logging.warning(f"[verify-email] no user found for hash prefix: {token_hash[:8]}")
        raise AuthenticationError("INVALID_TOKEN")
    if user.verification_token_expires_at < datetime.now(timezone.utc):
        raise AuthenticationError("TOKEN_EXPIRED")
    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    db.commit()
    return user


def generate_reset_token(db: Session, user: User) -> str:
    """Generate a password reset token, store its hash in DB, return the raw token."""
    raw_token = secrets.token_urlsafe(32)
    user.reset_password_token = _hash_token(raw_token)
    user.reset_password_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    return raw_token


def verify_reset_token(db: Session, raw_token: str) -> User:
    """Verify the reset token. Does NOT clear it — caller must do that after resetting."""
    token_hash = _hash_token(raw_token)
    user = db.query(User).filter(User.reset_password_token == token_hash).first()
    if not user:
        raise AuthenticationError("INVALID_TOKEN")
    if user.reset_password_token_expires_at < datetime.now(timezone.utc):
        raise AuthenticationError("TOKEN_EXPIRED")
    return user


def reset_user_password(db: Session, user: User, new_password: str) -> None:
    """Set a new password, clear the reset token, and invalidate all existing refresh tokens."""
    user.password_hash = get_password_hash(new_password)
    user.reset_password_token = None
    user.reset_password_token_expires_at = None
    user.refresh_token_hash = None
    if user.auth_method == 'google':
        user.auth_method = 'both'
    db.commit()


def get_verified_user(current_user: CurrentUser, db: DbSession) -> models.TokenData:
    """Dependency that ensures the authenticated user has verified their email."""
    user_id = current_user.get_uuid()
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail={"code": "EMAIL_NOT_VERIFIED", "message": "Please verify your email address to continue."}
        )
    return current_user


RequireVerified = Annotated[models.TokenData, Depends(get_verified_user)]


def logout_user(db: Session, refresh_token: str | None, settings: Settings) -> None:
    """Clear refresh token hash on logout so the token can no longer be used."""
    if not refresh_token:
        return
    try:
        token_data = verify_refresh_token(refresh_token, settings.jwt_secret_key, settings.algorithm)
        user = db.query(User).filter(User.id == token_data.get_uuid()).first()
        if user:
            user.refresh_token_hash = None
            db.commit()
    except Exception:
        pass  # Token already invalid — nothing to clear


def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                                 db: Session, settings: Settings) -> models.Token:
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise AuthenticationError()
    return create_token_pair(user, settings, db)  # Use token pair instead of single token


def google_authenticate_user(db: Session, user_info: dict, settings: Settings, google_tokens: dict = None) -> models.Token:
    """
    Authenticate or register a user using Google OAuth info.
    Returns a Token object with both access and refresh tokens.
    Stores Google OAuth tokens in database for API access.
    """
    email = user_info.get("email")
    first_name = user_info.get("given_name", "")
    last_name = user_info.get("family_name", "")
    google_id = user_info.get("sub")
    avatar_url = user_info.get("picture")
    
    if not email:
        logging.error("Google OAuth did not return an email.")
        raise AuthenticationError("Google OAuth did not return an email.")

    user = db.query(User).filter(User.email == email).first()
    
    if user:
        # Existing user - Login
        if not user.google_id and user.auth_method not in ('google', 'both'):
            logging.warning(f"User attempted Google login but is not authorized for Google login.")
            raise AuthenticationError("Google login not enabled for this user.")
        
        # Update auth_method based on existing credentials
        if user.password_hash and user.auth_method != 'both':
            user.auth_method = 'both'  # User has both password and Google
        elif not user.password_hash and user.auth_method != 'google':
            user.auth_method = 'google'  # User only has Google
            
        # Update google_id and avatar_url if not set
        if not user.google_id:
            user.google_id = google_id
        if avatar_url:
            user.avatar_url = avatar_url
        
        # Store Google OAuth tokens in database
        if google_tokens:
            access_raw = google_tokens.get('access_token')
            refresh_raw = google_tokens.get('refresh_token')
            if access_raw:
                user.google_access_token = encrypt_token(access_raw)
            if refresh_raw:
                user.google_refresh_token = encrypt_token(refresh_raw)
                logging.info(f"Stored new (encrypted) refresh token for user")
            expires_in = google_tokens.get('expires_in', 3600)
            user.google_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
        db.commit()
        db.refresh(user)
        logging.info(f"Authenticated existing user via Google OAuth")
    else:
        # New user - Registration
        user = User(
            id=uuid4(),
            email=email,
            first_name=first_name,
            last_name=last_name,
            google_id=google_id,
            auth_method='google',
            avatar_url=avatar_url,
            password_hash=None,
            google_access_token=(encrypt_token(google_tokens.get('access_token')) if google_tokens and google_tokens.get('access_token') else None),
            google_refresh_token=(encrypt_token(google_tokens.get('refresh_token')) if google_tokens and google_tokens.get('refresh_token') else None),
            google_token_expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=google_tokens.get('expires_in', 3600))
                if google_tokens else None
            )
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logging.info(f"Registered new user via Google OAuth")

    return create_token_pair(user, settings, db)  # Use token pair instead of single token


def change_password(db: Session, user_id: UUID, password_change: models.PasswordChange) -> None:
    """Change user password with validation."""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise AuthenticationError("User not found")
        
        # Verify current password
        if not verify_password(password_change.current_password, user.password_hash):
            raise AuthenticationError("Invalid current password")
        
        # Verify new passwords match
        if password_change.new_password != password_change.new_password_confirm:
            raise AuthenticationError("New passwords do not match")
        
        # Update password and invalidate all existing refresh tokens
        user.password_hash = get_password_hash(password_change.new_password)
        user.refresh_token_hash = None
        db.commit()
        logging.info(f"Successfully changed password for user ID: {user_id}")
    except Exception as e:
        logging.error(f"Error during password change for user ID: {user_id}. Error: {str(e)}")
        raise


def refresh_token_pair(refresh_token: str, db: Session, settings: Settings) -> models.Token:
    """Create new token pair using refresh token. Validates hash stored in DB."""
    token_data = verify_refresh_token(refresh_token, settings.jwt_secret_key, settings.algorithm)

    user = db.query(User).filter(User.id == token_data.get_uuid()).first()
    if not user:
        raise AuthenticationError("User not found")

    # Reject if hash doesn't match — token was invalidated (password change, logout, etc.)
    if not user.refresh_token_hash or user.refresh_token_hash != _hash_token(refresh_token):
        raise AuthenticationError("Invalid refresh token")

    return create_token_pair(user, settings, db)
