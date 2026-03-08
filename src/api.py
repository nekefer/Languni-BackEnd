from fastapi import FastAPI
from src.auth.controller import router as auth_router
from src.users.controller import router as users_router
from src.youtube.controller import router as youtube_router
from src.vocabulary.controller import router as vocabulary_router
from src.videos.controller import router as videos_router
from src.translate.controller import router as translate_router
from src.saved_videos.controller import router as saved_videos_router
from src.dictionary.controller import router as dictionary_router
from src.billing.controller import router as billing_router
from src.contact.controller import router as contact_router

def register_routes(app: FastAPI):
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(youtube_router)
    app.include_router(vocabulary_router)
    app.include_router(videos_router)
    app.include_router(translate_router)
    app.include_router(saved_videos_router)
    app.include_router(dictionary_router)
    app.include_router(billing_router)
    app.include_router(contact_router)