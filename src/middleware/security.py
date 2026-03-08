from fastapi import Request, HTTPException, status, Depends, Cookie
from fastapi.responses import Response
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from typing import Optional
import jwt
import logging

from ..config import get_settings
from ..database.core import get_db
from ..entities.user import User

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)  # Don't auto-error, we'll handle it


# async def verify_jwt_token(
#     credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
#     access_token: Optional[str] = Cookie(None),
#     db: Session = Depends(get_db)
# ) -> User:
#     """
#     Verify JWT token from either:
#     1. Authorization header (Bearer token)
#     2. Cookie (access_token)
    
#     Returns the authenticated User object.
#     Raises HTTPException if authentication fails.
#     """
#     settings = get_settings()
#     token = None
    
#     # Try to get token from Authorization header first
#     if credentials:
#         token = credentials.credentials
#     # Fallback to cookie
#     elif access_token:
#         token = access_token
    
#     if not token:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Not authenticated. Please log in.",
#             headers={"WWW-Authenticate": "Bearer"},
#         )
    
#     try:
#         # Decode JWT token
#         payload = jwt.decode(
#             token,
#             settings.secret_key,
#             algorithms=["HS256"]
#         )
        
#         # Extract user ID from token
#         user_id: str = payload.get("sub")
#         if user_id is None:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid authentication token"
#             )
        
#         # Get user from database
#         user = db.query(User).filter(User.id == int(user_id)).first()
#         if user is None:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="User not found"
#             )
        
#         return user
        
#     except jwt.ExpiredSignatureError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Token has expired. Please log in again.",
#         )
#     except jwt.InvalidTokenError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid authentication token",
#         )
#     except Exception as e:
#         logger.error(f"Token verification error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Authentication failed",
#         )


# async def optional_jwt_token(
#     credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
#     access_token: Optional[str] = Cookie(None),
#     db: Session = Depends(get_db)
# ) -> Optional[User]:
#     """
#     Optional JWT authentication - returns User if authenticated, None otherwise.
#     Useful for endpoints that work differently when authenticated but don't require it.
#     """
#     try:
#         return await verify_jwt_token(credentials, access_token, db)
#     except HTTPException:
#         return None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers to prevent common attacks
        security_headers = {
            # Prevent MIME type sniffing attacks
            "X-Content-Type-Options": "nosniff",
            
            # Prevent clickjacking attacks
            "X-Frame-Options": "DENY",
            
            # Enable XSS protection
            "X-XSS-Protection": "1; mode=block",
            
            # Control referrer information
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Prevent information disclosure
            "X-Permitted-Cross-Domain-Policies": "none",
            
            # Remove server information
            "Server": "",  # Remove server header
        }
        
        # Add HSTS in production (check config, not request scheme — proxy always forwards as http internally)
        settings = get_settings()
        if settings.is_production:
            security_headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # Update CSP to allow Swagger UI CDN
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://accounts.google.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "frame-src 'self' https://accounts.google.com; "
        )
        
        # Apply all security headers
        for header, value in security_headers.items():
            if value:  # Only set non-empty values
                response.headers[header] = value
        
        # Log security header application (in debug mode)
        logger.debug(f"Applied security headers to {request.method} {request.url.path}")
        
        return response
