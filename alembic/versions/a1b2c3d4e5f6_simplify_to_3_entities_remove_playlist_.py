"""simplify to 3 entities, remove playlist, add video FK

Revision ID: a1b2c3d4e5f6
Revises: 396ef840ac80
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '396ef840ac80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop playlists table if it exists (was never created via migration, but safety check)
    op.execute("DROP TABLE IF EXISTS playlists CASCADE")

    # Clear any non-integer video_id values before type conversion
    op.execute("UPDATE user_words SET video_id = NULL WHERE video_id IS NOT NULL AND video_id !~ '^[0-9]+$'")

    # Change video_id from String(255) to Integer
    op.alter_column(
        'user_words',
        'video_id',
        existing_type=sa.String(255),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using='video_id::integer'
    )

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_user_words_video_id',
        'user_words',
        'videos',
        ['video_id'],
        ['id']
    )


def downgrade() -> None:
    # Remove foreign key constraint
    op.drop_constraint('fk_user_words_video_id', 'user_words', type_='foreignkey')

    # Change video_id back from Integer to String(255)
    op.alter_column(
        'user_words',
        'video_id',
        existing_type=sa.Integer(),
        type_=sa.String(255),
        existing_nullable=True,
        postgresql_using='video_id::varchar'
    )
