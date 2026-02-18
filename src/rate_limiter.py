from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

# Initialize limiter with remote address as key
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],  # Global default
    storage_uri="memory://",  # In-memory storage (use Redis for production)
)

# Rate limit configurations for different endpoint categories
RATE_LIMITS = {
    # Authentication endpoints (strict limits)
    "auth_register": "5/minute",           # 5 registration attempts per minute
    "auth_login": "5/minute",            # 5 login attempts per minute
    "auth_refresh": "10/minute",         # 10 token refresh per minute
    "auth_google_login": "10/minute",    # 10 Google login initiations per minute
    "auth_google_callback": "20/minute", # 20 Google OAuth callbacks per minute
    "change-password" : "3/minute",      # 3 password changes per minute
    
    # Vocabulary endpoints (moderate limits)
    "vocabulary_save": "30/minute",      # 30 save requests per minute
    "vocabulary_get": "60/minute",       # 60 read requests per minute
    "vocabulary_delete": "20/minute",    # 20 delete requests per minute
    
    # YouTube endpoints (moderate limits)
    "youtube_trending": "30/minute",     # 30 trending requests per minute
    "youtube_captions": "60/minute",     # 60 caption requests per minute
    "youtube_liked": "20/minute",        # 20 liked video requests per minute
    
    # User endpoints (moderate limits)
    "user_profile": "60/minute",         # 60 profile requests per minute
    
    # Saved videos endpoints
    "saved_videos_save": "30/minute",    # 30 save requests per minute
    "saved_videos_get": "60/minute",     # 60 read requests per minute
    "saved_videos_delete": "20/minute",  # 20 delete requests per minute

    # Translation endpoints
    "translate": "30/minute",            # 30 translation requests per minute

    # General API (fallback)
    "general": "100/minute",             # 100 general requests per minute
}


async def rate_limit_error_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom error handler for rate limit exceeded errors."""
    logger.warning(
        f"Rate limit exceeded for {request.client.host} on {request.url.path}"
    )
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": "Too many requests. Please try again later.",
            "retry_after": exc.detail if hasattr(exc, 'detail') else "60 seconds"
        },
        headers={
            "Retry-After": "60",  # Suggest retry after 60 seconds
            "X-RateLimit-Limit": str(getattr(exc, 'limit', '100/minute')),
        }
    )