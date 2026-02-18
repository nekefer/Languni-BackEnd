"""remove_available_subtitles_from_videos

Revision ID: f3847a8219fc
Revises: b3c4d5e6f7a8
Create Date: 2026-02-17 18:26:37.603029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3847a8219fc'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('videos', 'available_subtitles')


def downgrade() -> None:
    op.add_column('videos', sa.Column('available_subtitles', sa.ARRAY(sa.String()), nullable=True))
