"""shift log: operator notes and shift handovers

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'shift_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('camera_id', sa.String(length=50), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('accepted_by', sa.String(length=50), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shift_entries_id'), 'shift_entries', ['id'], unique=False)
    op.create_index(op.f('ix_shift_entries_kind'), 'shift_entries', ['kind'], unique=False)
    op.create_index(op.f('ix_shift_entries_timestamp'), 'shift_entries', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_shift_entries_timestamp'), table_name='shift_entries')
    op.drop_index(op.f('ix_shift_entries_kind'), table_name='shift_entries')
    op.drop_index(op.f('ix_shift_entries_id'), table_name='shift_entries')
    op.drop_table('shift_entries')
