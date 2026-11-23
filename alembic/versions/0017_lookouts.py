"""lookouts (BOLO) and their cameras

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bolos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ref', sa.String(20), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('target_ref', sa.String(40)), sa.Column('payload', sa.Text()),
        sa.Column('origin', sa.String(12), nullable=False, server_default='auto'),
        sa.Column('origin_camera', sa.String(50)), sa.Column('direction', sa.String(4)), sa.Column('heading_deg', sa.Float()),
        sa.Column('incident_id', sa.Integer()), sa.Column('cross_track_id', sa.Integer()),
        sa.Column('reason', sa.Text()), sa.Column('case_no', sa.String(60)), sa.Column('created_by', sa.Integer()),
        sa.Column('ring', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(12), nullable=False, server_default='active'),
        sa.Column('found_camera', sa.String(50)), sa.Column('found_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
    for col, unique in (('id', False), ('ref', True), ('target_ref', False), ('incident_id', False),
                        ('cross_track_id', False), ('window_end', False), ('status', False)):
        op.create_index(f'ix_bolos_{col}', 'bolos', [col], unique=unique)
    op.create_table(
        'bolo_cameras',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bolo_id', sa.Integer(), sa.ForeignKey('bolos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('camera_id', sa.String(50), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ring', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('eta_from_s', sa.Float()), sa.Column('eta_to_s', sa.Float()), sa.Column('distance_m', sa.Float()),
        sa.Column('notified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_bolo_cameras_bolo_id', 'bolo_cameras', ['bolo_id'])
    op.create_index('ix_bolo_cameras_camera_id', 'bolo_cameras', ['camera_id'])


def downgrade() -> None:
    op.drop_table('bolo_cameras')
    op.drop_table('bolos')
