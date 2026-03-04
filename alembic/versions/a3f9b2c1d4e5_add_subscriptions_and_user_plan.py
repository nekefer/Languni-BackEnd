"""add_subscriptions_and_user_plan

Revision ID: a3f9b2c1d4e5
Revises: 445a72c3e158
Create Date: 2026-03-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a3f9b2c1d4e5'
down_revision = '445a72c3e158'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add subscription fields to users table
    op.add_column('users', sa.Column('subscription_plan', sa.String(20), nullable=False, server_default='free'))
    op.add_column('users', sa.Column('daily_video_views', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('daily_views_date', sa.Date(), nullable=True))

    # Create subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('ls_customer_id', sa.String(), nullable=True),
        sa.Column('ls_subscription_id', sa.String(), nullable=True, unique=True),
        sa.Column('ls_order_id', sa.String(), nullable=True),
        sa.Column('ls_variant_id', sa.String(), nullable=True),
        sa.Column('plan', sa.String(20), nullable=False, server_default='free'),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('subscriptions')
    op.drop_column('users', 'daily_views_date')
    op.drop_column('users', 'daily_video_views')
    op.drop_column('users', 'subscription_plan')
