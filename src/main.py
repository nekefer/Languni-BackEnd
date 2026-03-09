from fastapi import FastAPI
from .database.core import engine, Base
from .api import register_routes
from .logging import configure_logging, get_logger
from .config import get_settings
from .rate_limiter import limiter, rate_limit_error_handler
from .middleware.security import SecurityHeadersMiddleware
from .middleware.logging import RequestLoggingMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from slowapi.errors import RateLimitExceeded

# Initialize logging FIRST
configure_logging()

logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="Languni API",
    description="Language learning platform API with YouTube integration",
    version="1.0.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

# Add rate limiter state to app
app.state.limiter = limiter

# Add rate limit error handler
app.add_exception_handler(RateLimitExceeded, rate_limit_error_handler)

# Add middleware (order matters!)
app.add_middleware(RequestLoggingMiddleware)  # Log all requests
app.add_middleware(SecurityHeadersMiddleware)  # Add security headers

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type"],
)


register_routes(app)


@app.get("/health", tags=["monitoring"])
def health_check():
    """Health check endpoint for Vercel / uptime monitors"""
    from sqlalchemy import text
    from .database.core import SessionLocal

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_status = "ok"
    except Exception:
        db_status = "unavailable"

    return {
        "status": "ok",
        "database": db_status,
        "environment": settings.environment,
    }


@app.on_event("startup")
async def startup_event():
    """Log application startup"""
    logger.info(
        "Application started",
        extra={"environment": settings.environment, "debug": settings.is_development}
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Log application shutdown"""
    logger.info("Application shutting down")