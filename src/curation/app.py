"""Explicit local-only companion service. Not registered in the production API."""
import asyncio
from contextlib import asynccontextmanager
import ipaddress
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .schema import Language, Level, TOPICS
from .store import Store
from .service import discover, prepare, make_batch, lesson
from .service import candidate
from scripts.seed_videos import fetch_video_details, QuotaExhausted, YouTubeDiscoveryError
import httpx
from .publisher import publish_batch, target_label

ROOT = Path(__file__).resolve().parents[2]
# Local settings never change the application's database configuration.
CONFIG = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.curation"), **os.environ}
LOCAL = ROOT / ".curation"
lock = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    if CONFIG.get("ENVIRONMENT", "development") != "development" or os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        raise RuntimeError("The curation service must run on your local computer")
    app.state.store = Store(LOCAL / "review.sqlite3")
    # A terminated download can safely be retried; it is never auto-approved.
    for row in app.state.store.all():
        if row["state"] == "downloading":
            row.update(state="failed", error="Download interrupted. Retry locally.")
            app.state.store.save(row)
    yield


app = FastAPI(title="Languni local curation", lifespan=lifespan)
ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "X-Requested-With"])


@app.middleware("http")
async def local_only(request: Request, call_next):
    try:
        local_client = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local_client = False
    host = urlsplit("//" + request.headers.get("host", "")).hostname
    origin = request.headers.get("origin")
    if not local_client or host not in ("localhost", "127.0.0.1", "::1") or (origin and origin not in ORIGINS):
        return JSONResponse({"detail": "Curation is available only on this computer"}, status_code=403)
    if request.method not in ("GET", "OPTIONS") and request.headers.get("x-requested-with") != "LanguniCuration":
        return JSONResponse({"detail": "Local review header required"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


class Discovery(BaseModel):
    languages: list[Language] = Field(default=["en", "fr", "es"], min_length=1, max_length=3)
    topics: list[str] = Field(default=list(TOPICS), min_length=1, max_length=12)
    count: int = Field(default=5, ge=1, le=10)
    refresh: bool = False
    query: str | None = Field(default=None, max_length=200)

    @field_validator("topics")
    @classmethod
    def topics_known(cls, value):
        if any(topic not in TOPICS for topic in value):
            raise ValueError("Unknown interest")
        return list(dict.fromkeys(value))


class Decision(BaseModel):
    action: str = Field(pattern="^(approve|reject|ready|reopen)$")
    language: Language
    difficulty_level: Level
    topics: list[str] = Field(min_length=1, max_length=12)
    notes: str = Field(default="", max_length=2000)


class ManualCandidate(BaseModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    language: Language
    topic: str


class Selection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    preview_id: str | None = None

    @field_validator("ids")
    @classmethod
    def distinct(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Select each candidate only once")
        return value


def exclusive():
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Another curation operation is running. Wait for it to finish.")


@app.get("/candidates")
def candidates(request: Request):
    rows = request.app.state.store.all()
    return {"items": [{k: v for k, v in row.items() if k != "subtitles"} | {"caption_count": len(row.get("subtitles", []))} for row in rows],
            "publisher_configured": bool(CONFIG.get("PUBLISH_DATABASE_URL")), "busy": lock.locked()}


@app.get("/candidates/{video_id}")
def candidate_detail(video_id: str, request: Request):
    return request.app.state.store.get(video_id)


@app.post("/discover")
async def find_candidates(payload: Discovery, request: Request):
    key = CONFIG.get("YOUTUBE_API_KEY")
    if not key:
        raise HTTPException(400, "Set YOUTUBE_API_KEY in the backend .env.curation file")
    exclusive()
    try:
        return await discover(request.app.state.store, key, **payload.model_dump())
    except (QuotaExhausted, YouTubeDiscoveryError) as exc:
        raise HTTPException(502, str(exc)) from None
    except Exception as exc:
        raise HTTPException(502, f"Discovery stopped ({type(exc).__name__}). Existing candidates are saved. Check API access/quota and retry.") from None
    finally:
        lock.release()


@app.post("/candidate")
async def add_candidate(payload: ManualCandidate, request: Request):
    if payload.topic not in TOPICS:
        raise ValueError("Choose an interest")
    key = CONFIG.get("YOUTUBE_API_KEY")
    if not key:
        raise ValueError("Set YOUTUBE_API_KEY in .env.curation")
    exclusive()
    try:
        async with httpx.AsyncClient() as client:
            items = await fetch_video_details(client, key, [payload.video_id])
        row = candidate(items[0], payload.language, payload.topic) if items else None
        if row is None:
            raise ValueError("Video must be public, embeddable, 1–30 minutes, and in the selected language")
        request.app.state.store.save(row, new=True)
        return {"video_id": row["youtube_video_id"]}
    except (QuotaExhausted, YouTubeDiscoveryError) as exc:
        raise HTTPException(502, str(exc)) from None
    except httpx.RequestError:
        raise HTTPException(502, "Could not reach YouTube. Check this computer's network connection.") from None
    finally:
        lock.release()


@app.patch("/candidates/{video_id}")
def decide(video_id: str, payload: Decision, request: Request):
    exclusive()
    try:
        store = request.app.state.store
        row = store.get(video_id)
        if any(topic not in TOPICS for topic in payload.topics):
            raise ValueError("Unknown interest")
        if payload.action == "ready" and row["state"] != "needs_review":
            raise ValueError("Download and review the subtitles first")
        if payload.action == "approve" and row["state"] not in ("suggested", "rejected", "failed"):
            raise ValueError("Reopen the candidate before approving again")
        if payload.action == "ready" and payload.language != row.get("subtitle_language"):
            raise ValueError("Language changed. Reopen and download matching subtitles first")
        row.update(language=payload.language, difficulty_level=payload.difficulty_level, topics=sorted(set(payload.topics)), notes=payload.notes)
        row["state"] = {"approve": "approved", "reject": "rejected", "ready": "ready", "reopen": "suggested"}[payload.action]
        if payload.action == "ready":
            lesson(row)
        elif payload.action in ("approve", "reopen"):
            for key in ("subtitles", "subtitle_checksum", "subtitle_language", "subtitle_source", "subtitle_fetched_at"):
                row.pop(key, None)
            row.update(warnings=[], error=None)
        store.save(row)
        return row
    finally:
        lock.release()


@app.post("/prepare")
async def prepare_selected(payload: Selection, request: Request):
    exclusive()
    try:
        store = request.app.state.store
        if any(store.get(i)["state"] not in ("approved", "failed") for i in payload.ids):
            raise ValueError("Only approved or failed downloads can be prepared")
        rows = []
        for video_id in payload.ids:
            rows.append(await run_in_threadpool(prepare, store, video_id))
            await asyncio.sleep(0.5)
        return {"prepared": sum(row["state"] == "needs_review" for row in rows), "failed": sum(row["state"] == "failed" for row in rows)}
    finally:
        lock.release()


@app.post("/export")
def export_selected(payload: Selection, request: Request):
    return make_batch(request.app.state.store, payload.ids).model_dump(mode="json")


def publication(payload, store, write=False):
    url = CONFIG.get("PUBLISH_DATABASE_URL")
    if not url:
        raise ValueError("Set PUBLISH_DATABASE_URL in .env.curation to enable publication preview")
    target = target_label(url)
    batch = make_batch(store, payload.ids)
    engine = create_engine(url, connect_args={"connect_timeout": 10}, hide_parameters=True)
    try:
        report = publish_batch(engine, batch, target, payload.preview_id if write else None)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Could not complete the database operation. Check the connection and migration. No partial batch was committed; preview again to confirm destination state.") from None
    finally:
        engine.dispose()
    if write:
        # Record commit before local state changes; a retry is safe if this machine stops.
        receipt_dir = LOCAL / "receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / f"{report['preview_id']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        for video_id in payload.ids:
            row = store.get(video_id)
            row["state"] = "published"
            store.save(row)
    return report


@app.post("/publication/preview")
def preview(payload: Selection, request: Request):
    exclusive()
    try:
        return publication(payload, request.app.state.store)
    finally:
        lock.release()


@app.post("/publication/publish")
def publish(payload: Selection, request: Request):
    if not payload.preview_id:
        raise ValueError("Preview this batch before publishing")
    exclusive()
    try:
        return publication(payload, request.app.state.store, write=True)
    finally:
        lock.release()
