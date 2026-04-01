from typing import Annotated
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from starlette import status
import asyncio
from . import models
from . import service
from fastapi.security import OAuth2PasswordRequestForm
from ..database.core import DbSession
from ..rate_limiter import limiter
from ..exceptions import AuthenticationError
from .google.oauth_config import oauth  # fixed import
from ..config import get_settings, Settings
from ..entities.user import User
from ..email import service as email_service
import urllib.parse
import logging
from sqlalchemy.orm import Session
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

router = APIRouter(
    prefix='/auth',
    tags=['auth']
)

@router.post("/", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def register_user(
    request: Request, 
    db: DbSession,
    register_user_request: models.RegisterUserRequest,
    settings: Annotated[Settings, Depends(get_settings)]
):
    """Register user, send verification email, and automatically log them in."""
    # Create the user
    service.register_user(db, register_user_request)

    # Automatically log them in after registration
    user = db.query(User).filter(User.email == register_user_request.email).first()
    if not user:
        raise AuthenticationError("User creation failed")

    # Generate verification token and send email (non-blocking failure)
    try:
        raw_token = service.generate_verification_token(db, user)
        email_service.send_verification_email(
            first_name=user.first_name,
            to_email=user.email,
            raw_token=raw_token,
            frontend_url=settings.frontend_url,
        )
    except Exception as e:
        logging.error(f"Failed to send verification email to {user.email}: {e}")

    # Create token pair for the new user
    jwt_token = service.create_token_pair(user, settings, db)

    # Create response with success message
    response = JSONResponse(content={
        "message": "User registered successfully. Please check your email to verify your account.",
        "user": {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_verified": user.is_verified,
        }
    })
    
    # Set authentication cookies
    response.set_cookie(
        key="access_token",
        value=jwt_token.access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/"
    )
    
    response.set_cookie(
        key="refresh_token",
        value=jwt_token.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/"
    )
    
    # Set user info cookie for frontend - SECURE VERSION
    response.set_cookie(
        key="user_email",
        value=user.email,
        httponly=True,  # ✅ Prevent XSS access
        secure=settings.is_production,
        samesite="strict",  # ✅ Better CSRF protection
        max_age=24 * 60 * 60,  # 24 hours
        path="/"
    )
    
    return response


@router.post("/token", response_model=models.Token)
@limiter.limit("5/minute")  # ✅ Rate limiting for login attempts
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)]
):
    """Login endpoint that sets both access and refresh tokens."""
    token_data = service.login_for_access_token(form_data, db, settings)

    # Create response with token data
    response = JSONResponse(content={
        "access_token": token_data.access_token,
        "refresh_token": token_data.refresh_token,  # ✅ Add refresh token
        "token_type": token_data.token_type,
        "expires_in": token_data.expires_in
    })
    
    # Set both JWT tokens in HttpOnly cookies
    response.set_cookie(
        key="access_token",
        value=token_data.access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/"
    )
    
    # ✅ Add refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=token_data.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/"
    )
    
    return response

@router.get("/google/login")
async def google_login(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    """🎯 Unified Google OAuth - handles both registration and login automatically."""
    redirect_uri = settings.google_redirect_uri
    
    # Simple state parameter for CSRF protection (no intent needed)
    import secrets
    state = secrets.token_urlsafe(32)
    
    # access_type='offline' + prompt='consent' ensures we get a refresh_token
    # This allows us to refresh expired access tokens without user re-authentication
    return await oauth.google.authorize_redirect(
        request, 
        redirect_uri=redirect_uri, 
        state=state,
        access_type='offline',  # Request offline access (refresh token)
        prompt='consent'  # Force consent screen to get refresh token every time
    )


# Handle the OAuth callback from Google
@router.get("/google/callback")
async def google_auth(
    request: Request,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)]
):
    """
    🎯 Unified Google OAuth callback - automatically handles registration and login.
    No matter which page the user came from, this will:
    - Create account if user doesn't exist
    - Log in if user already exists
    """
    try:
        # Get full token response from Google (includes access_token, refresh_token, expires_in)
        token = await oauth.google.authorize_access_token(request)
        
        user_info = token.get("userinfo") or {}
        
        if not user_info:
            raise AuthenticationError("Google OAuth failed - no user info received")
        
        # Extract user info from the user_info dict
        user_email = user_info.get("email", "")
        
        # 🎯 UNIFIED GOOGLE OAUTH APPROACH
        # No matter if they came from login or register page:
        # - If user exists → Log them in
        # - If user doesn't exist → Create account and log them in
        # This eliminates confusing error messages!
        
        # Check if user exists
        existing_user = db.query(User).filter(User.email == user_email).first()
        is_new_user = existing_user is None
        
        # Pass full token dict to service (includes access_token, refresh_token, expires_in)
        jwt_token = service.google_authenticate_user(db, user_info, settings, google_tokens=token)

        # Google OAuth users are auto-verified (Google already confirmed their email)
        verified_user = db.query(User).filter(User.email == user_email).first()
        if verified_user and not verified_user.is_verified:
            verified_user.is_verified = True
            db.commit()

        # Create response with redirect to frontend
        # Always redirect to dashboard for seamless experience
        redirect_url = f"{settings.frontend_url}/dashboard"

        
        response = RedirectResponse(url=redirect_url)
        
        # Set JWT token in HttpOnly cookie
        response.set_cookie(
            key="access_token",
            value=jwt_token.access_token,
            httponly=True,
            secure=settings.is_production,  # Use secure cookies in production
            samesite="lax",
            max_age=3600,  # 1 hour
            path="/"
        )
        
        # ✅ Add refresh token cookie
        response.set_cookie(
            key="refresh_token",
            value=jwt_token.refresh_token,  # ✅ Add this
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
            path="/"
        )
        
        # Set user info in a separate cookie - SECURE VERSION
        response.set_cookie(
            key="user_email",
            value=user_email,
            httponly=True,  # ✅ Prevent XSS access
            secure=settings.is_production,
            samesite="strict",  # ✅ Better CSRF protection
            max_age=3600,
            path="/"
        )
        
        # Set user type cookie (new vs existing) - SECURE VERSION
        response.set_cookie(
            key="user_type",
            value="new" if is_new_user else "existing",
            httponly=True,  # ✅ Prevent XSS access
            secure=settings.is_production,
            samesite="strict",  # ✅ Better CSRF protection
            max_age=3600,
            path="/"
        )
        
        return response
        
    except KeyError:
        logging.error("Google OAuth failed — missing required field in token response")
        error_url = f"{settings.frontend_url}/?error=incomplete_oauth_data"
        return RedirectResponse(url=error_url)
    except AuthenticationError as e:
        logging.error(f"Google OAuth authentication failed: {str(e)}")
        error_url = f"{settings.frontend_url}/?error=authentication_failed"
        return RedirectResponse(url=error_url)
    except Exception:
        logging.error("Unexpected Google OAuth error", exc_info=True)
        error_url = f"{settings.frontend_url}/?error=server_error"
        return RedirectResponse(url=error_url)


@router.post("/google/one-tap")
@limiter.limit("10/minute")
async def google_one_tap(
    request: Request,
    body: models.GoogleOneTapRequest,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)]
):
    """Verify a Google One Tap credential JWT and log in or register the user."""
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            settings.google_client_id
        )

        if idinfo.get("aud") != settings.google_client_id:
            raise HTTPException(status_code=401, detail="Invalid credential audience")

        if not idinfo.get("email_verified"):
            raise HTTPException(status_code=401, detail="Google email not verified")

        user_info = {
            "email": idinfo.get("email"),
            "given_name": idinfo.get("given_name", ""),
            "family_name": idinfo.get("family_name", ""),
            "sub": idinfo.get("sub"),
            "picture": idinfo.get("picture"),
        }

        jwt_token = service.google_authenticate_user(db, user_info, settings)

        verified_user = db.query(User).filter(User.email == user_info["email"]).first()
        if verified_user and not verified_user.is_verified:
            verified_user.is_verified = True
            db.commit()

        response = JSONResponse(content={
            "email": verified_user.email,
            "first_name": verified_user.first_name,
            "last_name": verified_user.last_name,
            "avatar_url": verified_user.avatar_url,
            "auth_method": verified_user.auth_method,
            "is_verified": verified_user.is_verified,
            "subscription_plan": verified_user.subscription_plan or "free",
        })

        response.set_cookie(
            key="access_token",
            value=jwt_token.access_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.access_token_expire_minutes * 60,
            path="/"
        )
        response.set_cookie(
            key="refresh_token",
            value=jwt_token.refresh_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
            path="/"
        )

        return response

    except ValueError as e:
        logging.warning(f"Invalid Google One Tap credential: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logging.error("Unexpected error in Google One Tap", exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.get("/me", response_model=models.UserResponse)
@limiter.limit("60/minute")  # ✅ Rate limiting for user info requests
async def get_current_user_info(request: Request, current_user: service.CurrentUser, db: DbSession):
    """Get current user information."""
    try:
        user_id = current_user.get_uuid()
        if not user_id:
            raise AuthenticationError("Invalid user token")
        
        # ✅ Replace the broken function call with direct database query
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return models.UserResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            auth_method=user.auth_method,
            avatar_url=user.avatar_url,
            is_active=user.is_active,
            is_verified=user.is_verified,
            subscription_plan=user.subscription_plan or 'free',
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat()
        )
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logging.error(f"Unexpected error in get_current_user_info: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get user information")


@router.post("/logout")
@limiter.limit("10/minute")  # ✅ Rate limiting for logout attempts
async def logout(request: Request, db: DbSession, settings: Annotated[Settings, Depends(get_settings)]):
    """✅ UPDATED: Logout endpoint - clears all cookies including Google tokens."""
    try:
        # Invalidate refresh token in DB
        refresh_token = request.cookies.get("refresh_token")
        service.logout_user(db, refresh_token, settings)

        # Create response
        response = JSONResponse(content={"message": "Successfully logged out"})
        
        # Clear all auth cookies with proper settings
        response.delete_cookie(
            key="access_token",
            path="/",
            secure=settings.is_production,
            httponly=True,
            samesite="lax"
        )
        
        response.delete_cookie(
            key="refresh_token",
            path="/",
            secure=settings.is_production,
            httponly=True,
            samesite="lax"
        )
        
        response.delete_cookie(
            key="user_email",
            path="/",
            secure=settings.is_production,
            httponly=False,
            samesite="lax"
        )
        
        response.delete_cookie(
            key="user_type",
            path="/",
            secure=settings.is_production,
            httponly=False,
            samesite="lax"
        )
        
        return response
        
    except AuthenticationError as e:
        # User wasn't authenticated, but that's okay for logout
        logging.info(f"Logout attempted without valid authentication: {str(e)}")
        response = JSONResponse(content={"message": "Logged out"})
        # Clear cookies anyway
        response.delete_cookie(key="access_token", path="/")
        response.delete_cookie(key="refresh_token", path="/")
        response.delete_cookie(key="user_email", path="/")
        response.delete_cookie(key="user_type", path="/")
        return response
    except Exception as e:
        # Unexpected error during logout
        logging.error(f"Error during logout: {str(e)}", exc_info=True)
        response = JSONResponse(content={"message": "Logged out (some cleanup failed)"})
        # Clear cookies anyway
        response.delete_cookie(key="access_token", path="/")
        response.delete_cookie(key="refresh_token", path="/")
        response.delete_cookie(key="user_email", path="/")
        response.delete_cookie(key="user_type", path="/")
        
        return response


@router.put("/change-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")  # ✅ Rate limiting for password changes (very restrictive)
async def change_password(
    request: Request,
    password_change: models.PasswordChange,
    db: DbSession,
    current_user: service.CurrentUser
):
    """Change user password. Requires authentication."""
    try:
        service.change_password(db, current_user.get_uuid(), password_change)
        return {"message": "Password changed successfully"}
    except AuthenticationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Unexpected error in change_password: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to change password")


@router.post("/refresh")
@limiter.limit("10/minute")  # ✅ Rate limiting for token refresh
async def refresh_tokens(
    request: Request,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)]
):
    """✅ UPDATED: Refresh access token using refresh token (stateless)."""
    try:
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            raise HTTPException(status_code=401, detail="No refresh token provided")
        
        # ✅ Verify refresh token and get new token pair (no database lookup for token validation)
        new_tokens = service.refresh_token_pair(refresh_token, db, settings)
        
        # Create response
        response = JSONResponse(content={
            "access_token": new_tokens.access_token,
            "refresh_token": new_tokens.refresh_token,
            "token_type": new_tokens.token_type,
            "expires_in": new_tokens.expires_in
        })
        
        # Set new cookies
        response.set_cookie(
            key="access_token",
            value=new_tokens.access_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.access_token_expire_minutes * 60,
            path="/"
        )
        
        response.set_cookie(
            key="refresh_token",
            value=new_tokens.refresh_token,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
            path="/"
        )
        
        return response

    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logging.error(f"Unexpected error in refresh_tokens: {str(e)}", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.get("/verify-email")
async def verify_email(
    token: str,
    db: DbSession,
):
    """Verify email address using the token sent by email."""
    try:
        service.verify_email_token(db, token)
        return {"message": "Email verified successfully"}
    except AuthenticationError as e:
        error_code = str(e)
        if "TOKEN_EXPIRED" in error_code:
            raise HTTPException(
                status_code=400,
                detail={"code": "TOKEN_EXPIRED", "message": "This verification link has expired. Please request a new one."}
            )
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_TOKEN", "message": "Invalid verification link."}
        )
    except Exception as e:
        logging.error(f"Unexpected error in verify_email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Verification failed")


@router.post("/resend-verification")
@limiter.limit("3/hour")
async def resend_verification(
    request: Request,
    body: models.ResendVerificationRequest,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Resend verification email. Always returns success to avoid leaking whether an email exists."""
    user = db.query(User).filter(User.email == body.email).first()
    if user and not user.is_verified:
        try:
            raw_token = service.generate_verification_token(db, user)
            email_service.send_verification_email(
                first_name=user.first_name,
                to_email=user.email,
                raw_token=raw_token,
                frontend_url=settings.frontend_url,
            )
        except Exception as e:
            logging.error(f"Failed to resend verification email to {body.email}: {e}")
    else:
        await asyncio.sleep(0.5)
    return {"message": "If that email is registered and unverified, a new verification link has been sent."}


@router.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    body: models.ForgotPasswordRequest,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Send a password reset email. Always returns success to avoid leaking whether an email exists."""
    user = db.query(User).filter(User.email == body.email).first()
    if user and user.auth_method in ('password', 'both'):
        try:
            raw_token = service.generate_reset_token(db, user)
            email_service.send_reset_password_email(
                first_name=user.first_name,
                to_email=user.email,
                raw_token=raw_token,
                frontend_url=settings.frontend_url,
            )
        except Exception as e:
            logging.error(f"Failed to send reset email to {body.email}: {e}")
    else:
        await asyncio.sleep(0.5)
    return {"message": "If that email is associated with a password account, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    body: models.ResetPasswordRequest,
    db: DbSession,
):
    """Reset user password using the token from the reset email."""
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    try:
        user = service.verify_reset_token(db, body.token)
        service.reset_user_password(db, user, body.new_password)
        return {"message": "Password reset successfully. You can now log in with your new password."}
    except AuthenticationError as e:
        error_code = str(e)
        if "TOKEN_EXPIRED" in error_code:
            raise HTTPException(
                status_code=400,
                detail={"code": "TOKEN_EXPIRED", "message": "This reset link has expired. Please request a new one."}
            )
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_TOKEN", "message": "Invalid reset link."}
        )
    except Exception as e:
        logging.error(f"Unexpected error in reset_password: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset password")





