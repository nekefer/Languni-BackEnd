"""add video_type column

Revision ID: 396ef840ac80
Revises: 232c89f1ff94
Create Date: 2026-02-11 17:26:54.194295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '396ef840ac80'
down_revision: Union[str, None] = '232c89f1ff94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('videos', sa.Column('video_type', sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('videos', 'video_type')
