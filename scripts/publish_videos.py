"""Preview/exported batches locally; publication requires the exact preview ID."""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

from src.curation.publisher import publish_batch, target_label
from src.curation.schema import Batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--expect-preview", help="Exact preview_id from the preceding dry run")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.curation")
    if args.publish and not args.expect_preview:
        parser.error("--publish requires --expect-preview from a dry run")
    url = os.getenv("PUBLISH_DATABASE_URL")
    if not url:
        parser.error("Set PUBLISH_DATABASE_URL explicitly; the application's DB settings are never reused")
    engine = None
    try:
        target = target_label(url)
        batch = Batch.model_validate_json(args.batch.read_text(encoding="utf-8-sig"))
        engine = create_engine(url, connect_args={"connect_timeout": 10}, hide_parameters=True)
        report = publish_batch(engine, batch, target, args.expect_preview if args.publish else None)
        print(json.dumps(report, indent=2))
    except Exception as exc:
        # Driver errors can include credentials; never print the connection/traceback.
        parser.exit(1, f"Publication failed ({type(exc).__name__}). Check batch validation, destination access and migration; then preview again.\n")
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
