"""camera registry fields (protocol, sealed credentials, capabilities, status, heartbeat,
sampling, priority, ingest token) and the detections store

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

CAMERA_COLS = [
    sa.Column('protocol', sa.String(12), nullable=False, server_default='rtsp'),
    sa.Column('vendor', sa.String(30)),
    sa.Column('credentials', sa.LargeBinary()),
    sa.Column('credentials_encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('address', sa.String(200)),
    sa.Column('road_name', sa.String(120)),
    sa.Column('capabilities', sa.Text()),
    sa.Column('ir_mode', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('status', sa.String(10), nullable=False, server_default='unknown'),
    sa.Column('last_heartbeat', sa.DateTime(timezone=True)),
    sa.Column('sample_fps', sa.Float()),
    sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('ingest_token_hash', sa.String(64)),
]


def upgrade() -> None:
    with op.batch_alter_table('cameras') as b:
        for c in CAMERA_COLS:
            b.add_column(c)

    op.create_table(
        'detections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.String(40), nullable=False),
        sa.Column('camera_id', sa.String(50), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('source', sa.String(40)), sa.Column('track_id', sa.String(40)), sa.Column('bbox', sa.String(80)),
        sa.Column('crop', sa.LargeBinary()),
        sa.Column('crop_encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('full_frame_ref', sa.String(255)),
        sa.Column('plate_raw', sa.String(60)), sa.Column('plate_canonical', sa.String(60)),
        sa.Column('plate_confidence', sa.Float()),
        sa.Column('vehicle_type', sa.String(30)), sa.Column('color', sa.String(20)), sa.Column('color_secondary', sa.String(20)),
        sa.Column('make_model', sa.String(60)), sa.Column('attr_conf', sa.Text()),
        sa.Column('color_reliable', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('direction', sa.String(4)),
        sa.Column('embedding', sa.LargeBinary()), sa.Column('embedding_model', sa.String(40)),
        sa.Column('matched', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('match_ref', sa.String(40)), sa.Column('alert_id', sa.Integer()), sa.Column('incident_id', sa.Integer()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    for col, unique in (('id', False), ('event_id', True), ('camera_id', False), ('ts', False), ('kind', False),
                        ('track_id', False), ('plate_canonical', False), ('vehicle_type', False), ('color', False),
                        ('make_model', False), ('matched', False), ('incident_id', False), ('expires_at', False)):
        op.create_index(f'ix_detections_{col}', 'detections', [col], unique=unique)
    op.create_index('idx_detection_cam_ts', 'detections', ['camera_id', 'ts'])


def downgrade() -> None:
    op.drop_table('detections')
    with op.batch_alter_table('cameras') as b:
        for c in reversed(CAMERA_COLS):
            b.drop_column(c.name)
