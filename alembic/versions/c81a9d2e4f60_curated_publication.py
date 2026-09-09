"""Add reviewed publication metadata without publishing existing videos."""
from alembic import op
import sqlalchemy as sa

revision = "c81a9d2e4f60"
down_revision = "f7c91e2d3a04"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("channel_title", sa.String(), nullable=True),
        sa.Column("youtube_published_at", sa.String(), nullable=True),
        sa.Column("publication_status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("subtitle_language", sa.String(10), nullable=True),
        sa.Column("subtitle_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subtitle_checksum", sa.String(64), nullable=True),
    ):
        op.add_column("videos", column)
    # Existing rows were already learner-facing before the editorial workflow.
    # Preserve them; new imported rows are published explicitly by the publisher.
    op.execute("UPDATE videos SET publication_status = 'published' WHERE subtitles IS NOT NULL")
    op.create_index("ix_videos_publication_status", "videos", ["publication_status"])


def downgrade():
    op.drop_index("ix_videos_publication_status", table_name="videos")
    for name in ("subtitle_checksum", "subtitle_fetched_at", "subtitle_language", "publication_status", "youtube_published_at", "channel_title"):
        op.drop_column("videos", name)
