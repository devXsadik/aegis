"""capture basket table (never migrated before) and the encrypted flag on stored images

alert_captures existed only through the app's create_all; on a database built by migrations
alone it was missing. Created here if absent, otherwise just given the new column.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table('alert_captures'):
        op.create_table(
            'alert_captures',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.Column('alert_id', sa.Integer(), nullable=True),
            sa.Column('alert_type', sa.String(length=30), nullable=False),
            sa.Column('camera_id', sa.String(length=50), nullable=True),
            sa.Column('camera_location', sa.String(length=50), nullable=True),
            sa.Column('camera_name', sa.String(length=100), nullable=True),
            sa.Column('camera_lat', sa.Float(), nullable=True),
            sa.Column('camera_lng', sa.Float(), nullable=True),
            sa.Column('track_id', sa.Integer(), nullable=True),
            sa.Column('person_name', sa.String(length=100), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('width', sa.Integer(), nullable=True),
            sa.Column('height', sa.Integer(), nullable=True),
            sa.Column('source_width', sa.Integer(), nullable=True),
            sa.Column('source_height', sa.Integer(), nullable=True),
            sa.Column('bbox', sa.String(length=60), nullable=True),
            sa.Column('attributes', sa.Text(), nullable=True),
            sa.Column('image_data', sa.LargeBinary(), nullable=False),
            sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('content_sha256', sa.String(length=64), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_capture_alert_time', 'alert_captures', ['alert_id', 'timestamp'], unique=False)
        op.create_index(op.f('ix_alert_captures_alert_id'), 'alert_captures', ['alert_id'], unique=False)
        op.create_index(op.f('ix_alert_captures_id'), 'alert_captures', ['id'], unique=False)
        op.create_index(op.f('ix_alert_captures_timestamp'), 'alert_captures', ['timestamp'], unique=False)
    else:
        op.add_column('alert_captures', sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('person_images', sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('person_images') as batch:
        batch.drop_column('encrypted')
    with op.batch_alter_table('alert_captures') as batch:
        batch.drop_column('encrypted')
