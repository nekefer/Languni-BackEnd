from typing import Optional
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging


class DatabaseSettings(BaseModel):
    """Database configuration settings"""
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class AuthSettings(BaseModel):
    """Authentication and JWT configuration settings"""
    secret_key: str = Field(..., min_length=32, description="Application secret key for sessions")
    jwt_secret_key: str = Field(..., min_length=32, description="JWT signing secret key")
    session_secret_key: str = Field(..., min_length=32, description="Session middleware secret key")
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(default=30, description="JWT token expiration time in minutes")
    refresh_token_expire_days: int = Field(default=7, description="Refresh token expiration time in days")
    
    @field_validator('secret_key', 'jwt_secret_key', 'session_secret_key')
    @classmethod
    def validate_secret_keys(cls, v):
        if len(v) < 32:
            raise ValueError("Secret keys must be at least 32 characters long for security")
        return v


class GoogleOAuthSettings(BaseModel):
    """Google OAuth configuration settings"""
    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    redirect_uri: str = Field(..., description="Google OAuth redirect URI")
    authorization_url: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth",
        description="Google OAuth authorization URL"
    )
    token_url: str = Field(
        default="https://oauth2.googleapis.com/token",
        description="Google OAuth token URL"
    )
    scope: str = Field(
        default="openid email profile",
        description="Google OAuth scopes"
    )
    server_metadata_url: str = Field(
        default="https://accounts.google.com/.well-known/openid-configuration",
        description="Google OAuth server metadata URL"
    )


class AppSettings(BaseModel):
    """General application settings"""
    environment: str = Field(default="development", description="Application environment")
    frontend_url: str = Field(..., description="Frontend application URL")
    log_level: str = Field(default="INFO", description="Logging level")
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(valid_levels)}")
        return v.upper()
    
    @field_validator('environment')
    @classmethod
    def validate_environment(cls, v):
        valid_envs = ['development', 'staging', 'production']
        if v.lower() not in valid_envs:
            raise ValueError(f"ENVIRONMENT must be one of: {', '.join(valid_envs)}")
        return v.lower()


class Settings(BaseSettings):
    """Main settings class that combines all configuration sections"""
    
    # Database settings
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(..., alias="DB_NAME")
    db_user: str = Field(..., alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    
    # Auth settings
    secret_key: str = Field(..., alias="SECRET_KEY")
    jwt_secret_key: str = Field(..., alias="JWT_SECRET_KEY")
    session_secret_key: str = Field(..., alias="SESSION_SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    
    # Google OAuth settings
    google_client_id: str = Field(..., alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(..., alias="GOOGLE_REDIRECT_URI")
    google_authorization_url: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth",
        alias="GOOGLE_AUTHORIZATION_URL"
    )
    
    # YouTube API settings
    youtube_api_key: str = Field(..., alias="YOUTUBE_API_KEY")
    
    # Encryption settings
    google_token_enc_key: str = Field(..., alias="GOOGLE_TOKEN_ENC_KEY")

    # SendGrid email settings
    sendgrid_api_key: str = Field(default="", alias="SENDGRID_API_KEY")
    sendgrid_from_email: str = Field(default="", alias="SENDGRID_FROM_EMAIL")

    # Lemon Squeezy billing settings
    lemon_squeezy_api_key: str = Field(default="", alias="LEMON_SQUEEZY_API_KEY")
    lemon_squeezy_store_id: str = Field(default="", alias="LEMON_SQUEEZY_STORE_ID")
    lemon_squeezy_monthly_variant_id: str = Field(default="", alias="LEMON_SQUEEZY_MONTHLY_VARIANT_ID")
    lemon_squeezy_yearly_variant_id: str = Field(default="", alias="LEMON_SQUEEZY_YEARLY_VARIANT_ID")
    lemon_squeezy_webhook_secret: str = Field(default="", alias="LEMON_SQUEEZY_WEBHOOK_SECRET")

    # App settings
    environment: str = Field(default="development", alias="ENVIRONMENT")
    frontend_url: str = Field(..., alias="FRONTEND_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @property
    def database(self) -> DatabaseSettings:
        """Get database settings as a structured object"""
        return DatabaseSettings(
            host=self.db_host,
            port=self.db_port,
            name=self.db_name,
            user=self.db_user,
            password=self.db_password,
        )
    
    @property
    def auth(self) -> AuthSettings:
        """Get auth settings as a structured object"""
        return AuthSettings(
            secret_key=self.secret_key,
            jwt_secret_key=self.jwt_secret_key,
            session_secret_key=self.session_secret_key,
            algorithm=self.algorithm,
            access_token_expire_minutes=self.access_token_expire_minutes,
            refresh_token_expire_days=self.refresh_token_expire_days
        )
    
    @property
    def google_oauth(self) -> GoogleOAuthSettings:
        """Get Google OAuth settings as a structured object"""
        return GoogleOAuthSettings(
            client_id=self.google_client_id,
            client_secret=self.google_client_secret,
            redirect_uri=self.google_redirect_uri,
            authorization_url=self.google_authorization_url
        )
    
    @property
    def app(self) -> AppSettings:
        """Get app settings as a structured object"""
        return AppSettings(
            environment=self.environment,
            frontend_url=self.frontend_url,
            log_level=self.log_level
        )
    
    @property
    def cors_origins(self) -> list[str]:
        """Get CORS origins based on environment"""
        base_origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173"
        ]
        
        if self.environment == "production":
            base_origins.extend([
                self.frontend_url,
                "https://languni.dev",
                "https://www.languni.dev",
            ])

        return base_origins
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.environment == "development"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode"""
        return self.environment == "production"


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance (singleton pattern)"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_logging_level() -> int:
    """Get the appropriate logging level for the Python logging module"""
    settings = get_settings()
    return getattr(logging, settings.log_level, logging.INFO)