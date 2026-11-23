"""case evidence uploads with custody chain, evidence face folders

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'evidence_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ref', sa.String(20), nullable=False),
        sa.Column('incident_id', sa.Integer(), sa.ForeignKey('incidents.id'), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('description', sa.Text()),
        sa.Column('location', sa.String(200)), sa.Column('lat', sa.Float()), sa.Column('lng', sa.Float()),
        sa.Column('captured_at', sa.DateTime(timezone=True)), sa.Column('camera_id', sa.String(50)),
        sa.Column('original_filename', sa.String(255)), sa.Column('content_type', sa.String(100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('storage_path', sa.String(400), nullable=False),
        sa.Column('encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('evidence_items.id')),
        sa.Column('source', sa.String(12), nullable=False, server_default='upload'),
        sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('device_info', sa.String(300)),
        sa.Column('faces_status', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('faces_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deleted_at', sa.DateTime(timezone=True)), sa.Column('deleted_by', sa.Integer()), sa.Column('delete_reason', sa.Text()),
    )
    for c, u in (('id', False), ('ref', True), ('incident_id', False), ('kind', False), ('captured_at', False),
                 ('sha256', False), ('parent_id', False), ('uploaded_by', False), ('uploaded_at', False)):
        op.create_index(f'ix_evidence_items_{c}', 'evidence_items', [c], unique=u)
    op.create_table(
        'evidence_item_custody',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('evidence_items.id'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False), sa.Column('actor', sa.String(80), nullable=False),
        sa.Column('actor_id', sa.Integer()), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('prev_hash', sa.String(64)), sa.Column('record_hash', sa.String(64), nullable=False),
        sa.Column('details', sa.Text()), sa.Column('ip_address', sa.String(45)),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_evidence_item_custody_id', 'evidence_item_custody', ['id'])
    op.create_index('ix_evidence_item_custody_item_id', 'evidence_item_custody', ['item_id'])
    op.create_table(
        'person_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(20), nullable=False), sa.Column('name', sa.String(120)),
        sa.Column('status', sa.String(20), nullable=False, server_default='unknown'),
        sa.Column('known_person_id', sa.Integer(), sa.ForeignKey('known_persons.id', ondelete='SET NULL')),
        sa.Column('best_face_id', sa.Integer()), sa.Column('first_seen', sa.DateTime(timezone=True)),
        sa.Column('last_seen', sa.DateTime(timezone=True)), sa.Column('merged_into', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_person_groups_id', 'person_groups', ['id'])
    op.create_index('ix_person_groups_code', 'person_groups', ['code'], unique=True)
    op.create_index('ix_person_groups_known_person_id', 'person_groups', ['known_person_id'])
    op.create_table(
        'evidence_faces',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('evidence_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('frame_ts', sa.Float()), sa.Column('bbox', sa.String(80)),
        sa.Column('crop', sa.LargeBinary(), nullable=False),
        sa.Column('crop_encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('embedding', sa.LargeBinary(), nullable=False), sa.Column('embedding_model', sa.String(40), nullable=False),
        sa.Column('quality', sa.Float()),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('person_groups.id', ondelete='SET NULL')),
        sa.Column('group_similarity', sa.Float()), sa.Column('watch_person_id', sa.Integer()), sa.Column('watch_similarity', sa.Float()),
        sa.Column('verify_status', sa.String(10)), sa.Column('verified_by', sa.Integer()),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    for c in ('id', 'item_id', 'group_id', 'watch_person_id'):
        op.create_index(f'ix_evidence_faces_{c}', 'evidence_faces', [c])
    op.create_table(
        'person_group_ops',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('op', sa.String(12), nullable=False), sa.Column('actor_id', sa.Integer()), sa.Column('actor', sa.String(80)),
        sa.Column('details', sa.Text()),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_person_group_ops_id', 'person_group_ops', ['id'])


def downgrade() -> None:
    op.drop_table('person_group_ops')
    op.drop_table('evidence_faces')
    op.drop_table('person_groups')
    op.drop_table('evidence_item_custody')
    op.drop_table('evidence_items')
