import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, JSON, DateTime, select, event
from pydantic import ValidationError

from src.curation.schema import Batch, digest
from src.curation.publisher import publish_batch, target_label
from src.curation.store import Store
from src.curation.service import candidate, prepare, make_batch, discover
from src.curation import app as local


def sample(video_id="abcdefghijk"):
    captions = [{"text": "Bonjour à tous", "start": 0.0, "duration": 30.0}, {"text": "Apprenons ensemble", "start": 30.0, "duration": 30.0}]
    return {"youtube_video_id": video_id, "title": "Sample lesson", "channel_title": "Sample channel",
            "youtube_published_at": "2025-01-01T00:00:00+00:00", "language": "fr", "topics": ["education"],
            "difficulty_level": "beginner", "duration_seconds": 60,
            "subtitle_language": "fr", "subtitle_source": "youtube_manual",
            "subtitle_fetched_at": "2026-09-09T00:00:00+00:00", "subtitles": captions,
            "subtitle_checksum": digest(captions), "reviewed": True}


class ValidationTests(unittest.TestCase):
    def test_rejects_tampering_wrong_language_and_duplicate_ids(self):
        for mutate in (
            lambda x: x.update(subtitle_language="es"),
            lambda x: x.update(subtitle_checksum="bad"),
            lambda x: x.update(reviewed=False),
            lambda x: x.update(topics=["unrecognized"]),
        ):
            row = sample(); mutate(row)
            with self.assertRaises(ValidationError):
                Batch(lessons=[row])
        with self.assertRaises(ValidationError):
            Batch(lessons=[sample(), sample()])

    def test_rejects_malformed_timestamps_even_with_matching_checksum(self):
        for start, duration in ((float("nan"), 2), (-1, 2), (1000, 2), (1, 0)):
            row = sample()
            row["subtitles"][0].update(start=start, duration=duration)
            row["subtitle_checksum"] = digest(row["subtitles"])
            with self.assertRaises(ValidationError):
                Batch(lessons=[row])

    def test_external_target_hides_password_and_rejects_private_domain(self):
        self.assertEqual(target_label("postgresql://editor:SECRET@example.com:1234/railway"), "example.com:1234/railway")
        with self.assertRaises(ValueError):
            target_label("postgresql://editor:SECRET@postgres.railway.internal/railway")


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        metadata = MetaData()
        self.videos = Table("videos", metadata, Column("id", Integer, primary_key=True),
            Column("youtube_video_id", String, unique=True),
            *[Column(key, String) for key in ("title", "url", "thumbnail_url", "channel_title", "youtube_published_at", "language", "difficulty_level", "video_type", "subtitle_language", "subtitle_checksum", "publication_status")],
            Column("topics", JSON), Column("subtitles", JSON), Column("subtitle_fetched_at", DateTime), Column("updated_at", DateTime),
            Column("unrelated_field", String, server_default="preserve"))
        self.users = Table("users", metadata, Column("id", Integer, primary_key=True), Column("name", String))
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(self.users.insert().values(id=1, name="Existing learner"))

    def tearDown(self):
        self.engine.dispose()

    def test_preview_then_publish_repeat_preserves_ids_and_users(self):
        batch = Batch(lessons=[sample()])
        plan = publish_batch(self.engine, batch, "test/database")
        with self.engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(self.videos)).all()), 0)
        publish_batch(self.engine, batch, "test/database", plan["preview_id"])
        plan2 = publish_batch(self.engine, batch, "test/database")
        self.assertEqual(plan2["changes"][0]["action"], "unchanged")
        row = sample(); row["title"] = "Reviewed title"
        updated = Batch(lessons=[row])
        plan3 = publish_batch(self.engine, updated, "test/database")
        publish_batch(self.engine, updated, "test/database", plan3["preview_id"])
        with self.engine.connect() as conn:
            records = conn.execute(select(self.videos)).mappings().all()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["id"], 1)
            self.assertEqual(records[0]["unrelated_field"], "preserve")
            self.assertEqual(conn.execute(select(self.users.c.name)).scalar(), "Existing learner")

    def test_changed_batch_or_target_requires_new_preview(self):
        batch = Batch(lessons=[sample()])
        preview = publish_batch(self.engine, batch, "test/database")
        with self.assertRaises(ValueError):
            publish_batch(self.engine, batch, "another/database", preview["preview_id"])
        changed = sample(); changed["title"] = "Changed"
        with self.assertRaises(ValueError):
            publish_batch(self.engine, Batch(lessons=[changed]), "test/database", preview["preview_id"])

    def test_failure_on_second_insert_rolls_back_entire_batch(self):
        batch = Batch(lessons=[sample(), sample("lmnopqrstuv")])
        plan = publish_batch(self.engine, batch, "test/database")
        inserts = []
        def fail(conn, cursor, statement, params, context, many):
            if statement.startswith("INSERT INTO videos"):
                inserts.append(statement)
                if len(inserts) == 2:
                    raise RuntimeError("Simulated interrupted batch")
        event.listen(self.engine, "before_cursor_execute", fail)
        with self.assertRaises(RuntimeError):
            publish_batch(self.engine, batch, "test/database", plan["preview_id"])
        event.remove(self.engine, "before_cursor_execute", fail)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.videos)).all(), [])


class LocalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "queue.sqlite3")
        self.patch_local = patch.object(local, "LOCAL", Path(self.temp.name))
        self.patch_config = patch.dict(local.CONFIG, {"ENVIRONMENT": "development", "YOUTUBE_API_KEY": "test"})
        self.patch_local.start(); self.patch_config.start()
        self.client = TestClient(local.app, base_url="http://127.0.0.1:8010", client=("127.0.0.1", 1234))
        self.client.__enter__()
        self.store = local.app.state.store
        row = sample() | {"state": "suggested", "notes": "", "reason": "test", "warnings": []}
        for key in ("subtitles", "subtitle_checksum", "subtitle_fetched_at", "subtitle_source", "subtitle_language", "reviewed"):
            row.pop(key, None)
        self.store.save(row)
        self.headers = {"X-Requested-With": "LanguniCuration", "Origin": "http://localhost:5173"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.patch_config.stop(); self.patch_local.stop(); self.temp.cleanup()

    def decision(self, action):
        return self.client.patch("/candidates/abcdefghijk", headers=self.headers, json={"action": action, "language": "fr", "difficulty_level": "beginner", "topics": ["education"]})

    def test_only_loopback_and_trusted_origin_can_mutate(self):
        self.assertEqual(self.client.post("/prepare", json={"ids": ["abcdefghijk"]}).status_code, 403)
        self.assertEqual(self.client.get("/candidates", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/candidates", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/candidates").status_code, 200)

    def test_approval_download_review_export_and_rejection(self):
        with patch("src.curation.service.YouTubeTranscriptApi") as api:
            response = self.client.post("/prepare", headers=self.headers, json={"ids": ["abcdefghijk"]})
            self.assertEqual(response.status_code, 400)
            api.assert_not_called()
            self.assertEqual(self.decision("ready").status_code, 400)
            self.assertEqual(self.decision("approve").status_code, 200)
            track = MagicMock(language_code="fr-FR", is_generated=False)
            track.fetch.return_value = [type("Snippet", (), c)() for c in sample()["subtitles"]]
            api.return_value.list.return_value = [track]
            response = self.client.post("/prepare", headers=self.headers, json={"ids": ["abcdefghijk"]})
            self.assertEqual(response.json()["prepared"], 1)
        self.assertEqual(self.store.get("abcdefghijk")["state"], "needs_review")
        self.assertEqual(self.client.post("/export", headers=self.headers, json={"ids": ["abcdefghijk"]}).status_code, 400)
        self.assertEqual(self.decision("ready").status_code, 200)
        exported = self.client.post("/export", headers=self.headers, json={"ids": ["abcdefghijk"]})
        self.assertEqual(exported.status_code, 200)
        Batch.model_validate(exported.json())
        self.decision("reject")
        with self.assertRaises(ValueError):
            make_batch(self.store, ["abcdefghijk"])

    def test_wrong_language_download_fails_without_ready_state(self):
        self.decision("approve")
        with patch("src.curation.service.YouTubeTranscriptApi") as api:
            api.return_value.list.return_value = [MagicMock(language_code="en", is_generated=False)]
            result = prepare(self.store, "abcdefghijk")
        self.assertEqual(result["state"], "failed")
        with self.assertRaises(ValueError):
            make_batch(self.store, ["abcdefghijk"])

    def test_discovery_is_cached_and_does_not_download(self):
        item = {"id": "lmnopqrstuv", "snippet": {"title": "French lesson", "publishedAt": "2025-01-01T00:00:00Z", "defaultAudioLanguage": "fr"}, "contentDetails": {"duration": "PT5M"}, "status": {"privacyStatus": "public", "embeddable": True}}
        with patch("src.curation.service.search_videos", return_value=[item["id"]]) as search, patch("src.curation.service.fetch_video_details", return_value=[item]), patch("src.curation.service.YouTubeTranscriptApi") as api:
            first = asyncio.run(discover(self.store, "key", ["fr"], ["education"]))
            second = asyncio.run(discover(self.store, "key", ["fr"], ["education"]))
            self.assertEqual(first["added"], 1)
            self.assertEqual(second["added"], 0)
            self.assertEqual(search.call_count, 1)
            api.assert_not_called()
        item["snippet"]["defaultAudioLanguage"] = "en"
        self.assertIsNone(candidate(item, "fr", "education"))


if __name__ == "__main__":
    unittest.main()
