"""two-factor sign-in (TOTP) on users

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('totp_last_step', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('totp_last_step')
        batch.drop_column('totp_enabled')
        batch.drop_column('totp_secret')
