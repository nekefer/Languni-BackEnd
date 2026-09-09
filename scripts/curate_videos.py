"""Run with python -m scripts.curate_videos from the backend directory."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.curation.app:app", host="127.0.0.1", port=8010, proxy_headers=False)
