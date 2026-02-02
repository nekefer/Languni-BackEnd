# Linguini Backend

FastAPI backend for Linguini - a language learning app that helps people learn **English, Spanish, or French** through interactive YouTube videos and songs.

## Features

- JWT authentication with HttpOnly cookies (password + Google OAuth)
- YouTube Data API integration for videos, songs, and captions
- User vocabulary tracking
- Level-based content recommendations
- Progress tracking

## Requirements

- Python 3.12+
- PostgreSQL database
- Google Cloud Console project (for OAuth and YouTube API)

## Installation

1. **Clone and navigate to the backend directory**
   ```bash
   cd Linguini-BackEnd
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv venv

   # Windows (Git Bash)
   source venv/Scripts/activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Set up environment variables**

   Create a `.env` file in the root directory:
   ```env
   # Database
   DATABASE_URL=postgresql://user:password@localhost:5432/linguini

   # Auth (generate secure 32+ character strings)
   SECRET_KEY=your-secret-key-here
   JWT_SECRET_KEY=your-jwt-secret-key-here
   SESSION_SECRET_KEY=your-session-secret-key-here

   # Google OAuth
   GOOGLE_CLIENT_ID=your-google-client-id
   GOOGLE_CLIENT_SECRET=your-google-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

   # YouTube API
   YOUTUBE_API_KEY=your-youtube-api-key

   # Token encryption (Fernet key)
   GOOGLE_TOKEN_ENC_KEY=your-fernet-key

   # App settings
   FRONTEND_URL=http://localhost:5173
   ENVIRONMENT=development
   ```

5. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

6. **Start the development server**
   ```bash
   uvicorn src.main:app --reload --port 8000
   ```

   The API will be available at `http://localhost:8000`

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
