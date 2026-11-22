"""floor plans on the operations map

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'floor_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('content_type', sa.String(length=30), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('south', sa.Float(), nullable=False),
        sa.Column('west', sa.Float(), nullable=False),
        sa.Column('north', sa.Float(), nullable=False),
        sa.Column('east', sa.Float(), nullable=False),
        sa.Column('opacity', sa.Float(), nullable=False, server_default='0.75'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_floor_plans_id', 'floor_plans', ['id'])


def downgrade() -> None:
    op.drop_index('ix_floor_plans_id', table_name='floor_plans')
    op.drop_table('floor_plans')
