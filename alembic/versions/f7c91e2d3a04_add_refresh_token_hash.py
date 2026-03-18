"""add refresh_token_hash to users

Revision ID: f7c91e2d3a04
Revises: 3e4ceeaa1720
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7c91e2d3a04'
down_revision: Union[str, None] = '3e4ceeaa1720'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('refresh_token_hash', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'refresh_token_hash')
