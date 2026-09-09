"""Independent SQLite review queue. Never opens the application's database."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS searches (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM candidates ORDER BY rowid DESC")]

    def get(self, video_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM candidates WHERE id = ?", (video_id,)).fetchone()
        if not row:
            raise ValueError("Candidate not found")
        return json.loads(row[0])

    def save(self, item, new=False):
        with self.connect() as db:
            if new:
                db.execute("INSERT OR IGNORE INTO candidates VALUES (?, ?)", (item["youtube_video_id"], json.dumps(item)))
            else:
                db.execute("INSERT INTO candidates VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (item["youtube_video_id"], json.dumps(item)))

    def cached_search(self, key):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM searches WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_search(self, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO searches VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (key, json.dumps(value)))
