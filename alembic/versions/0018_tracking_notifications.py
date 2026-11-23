"""camera graph, cross-camera tracks and hops, notifications

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'camera_edges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('from_camera', sa.String(50), nullable=False), sa.Column('to_camera', sa.String(50), nullable=False),
        sa.Column('distance_m', sa.Float(), nullable=False), sa.Column('travel_s', sa.Float(), nullable=False),
        sa.Column('bearing_deg', sa.Float()), sa.Column('road_name', sa.String(120)),
        sa.Column('bidirectional', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auto_suggested', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.UniqueConstraint('from_camera', 'to_camera', name='uq_camera_edge'),
    )
    for c in ('id', 'from_camera', 'to_camera'):
        op.create_index(f'ix_camera_edges_{c}', 'camera_edges', [c])
    op.create_table(
        'cross_camera_tracks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('target_ref', sa.String(40), nullable=False),
        sa.Column('incident_id', sa.Integer()),
        sa.Column('status', sa.String(10), nullable=False, server_default='active'),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_camera', sa.String(50)), sa.Column('last_seen', sa.DateTime(timezone=True)),
        sa.Column('direction', sa.String(4)), sa.Column('bearing', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    for c in ('id', 'target_ref', 'incident_id', 'status', 'last_seen'):
        op.create_index(f'ix_cross_camera_tracks_{c}', 'cross_camera_tracks', [c])
    op.create_table(
        'track_hops',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('cross_camera_tracks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('camera_id', sa.String(50), nullable=False), sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('direction', sa.String(4)), sa.Column('bearing', sa.Float()), sa.Column('method', sa.String(20)),
        sa.Column('confidence', sa.Float()), sa.Column('detection_id', sa.Integer()), sa.Column('alert_id', sa.Integer()),
        sa.Column('bolo_ref', sa.String(20)),
        sa.Column('consistent', sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column('note', sa.Text()),
    )
    op.create_index('ix_track_hops_track_id', 'track_hops', ['track_id'])
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False), sa.Column('priority', sa.String(10), nullable=False, server_default='high'),
        sa.Column('title', sa.String(200), nullable=False), sa.Column('body', sa.Text()), sa.Column('payload', sa.Text()),
        sa.Column('incident_id', sa.Integer()), sa.Column('alert_id', sa.Integer()), sa.Column('channels', sa.String(60)),
        sa.Column('dedup_key', sa.String(120)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('read_at', sa.DateTime(timezone=True)), sa.Column('ack_state', sa.String(14)),
        sa.Column('acked_at', sa.DateTime(timezone=True)), sa.Column('ack_deadline', sa.DateTime(timezone=True)),
        sa.Column('escalated_at', sa.DateTime(timezone=True)),
    )
    for c in ('id', 'user_id', 'incident_id', 'alert_id', 'dedup_key', 'created_at', 'ack_deadline'):
        op.create_index(f'ix_notifications_{c}', 'notifications', [c])


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('track_hops')
    op.drop_table('cross_camera_tracks')
    op.drop_table('camera_edges')
