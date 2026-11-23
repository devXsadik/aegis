"""datasets, dataset items, model registry, review queue

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'datasets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False), sa.Column('task', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(10), nullable=False, server_default='draft'),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('datasets.id')), sa.Column('classes', sa.Text()),
        sa.Column('split_seed', sa.Integer()), sa.Column('notes', sa.Text()), sa.Column('created_by', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('frozen_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('name', 'version', name='uq_dataset_version'),
    )
    op.create_index('ix_datasets_id', 'datasets', ['id'])
    op.create_table(
        'dataset_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('path', sa.String(400), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer()), sa.Column('height', sa.Integer()), sa.Column('split', sa.String(5)),
        sa.Column('day_night', sa.String(5)), sa.Column('source', sa.String(20), nullable=False),
        sa.Column('labels', sa.Text()), sa.Column('labeled_by', sa.Integer()), sa.Column('labeled_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    for c in ('id', 'dataset_id', 'sha256', 'split'):
        op.create_index(f'ix_dataset_items_{c}', 'dataset_items', [c])
    op.create_table(
        'model_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task', sa.String(20), nullable=False), sa.Column('name', sa.String(80), nullable=False),
        sa.Column('version', sa.String(30), nullable=False), sa.Column('metrics', sa.Text()),
        sa.Column('dataset_id', sa.Integer(), sa.ForeignKey('datasets.id')),
        sa.Column('artifact_path', sa.String(400), nullable=False), sa.Column('labels_path', sa.String(400)),
        sa.Column('format', sa.String(10), nullable=False), sa.Column('sha256', sa.String(64)),
        sa.Column('stage', sa.String(12), nullable=False, server_default='staging'), sa.Column('notes', sa.Text()),
        sa.Column('created_by', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('promoted_by', sa.Integer()), sa.Column('promoted_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('task', 'version', name='uq_model_task_version'),
    )
    for c in ('id', 'task', 'stage'):
        op.create_index(f'ix_model_versions_{c}', 'model_versions', [c])
    op.create_table(
        'review_queue',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('reason', sa.String(20), nullable=False),
        sa.Column('field', sa.String(20)), sa.Column('predicted', sa.String(80)), sa.Column('corrected', sa.String(80)),
        sa.Column('note', sa.Text()), sa.Column('alert_id', sa.Integer()), sa.Column('detection_id', sa.Integer()),
        sa.Column('crop', sa.LargeBinary()),
        sa.Column('crop_encrypted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('day_night', sa.String(5)), sa.Column('score', sa.Float()), sa.Column('created_by', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('status', sa.String(10), nullable=False, server_default='open'), sa.Column('dataset_item_id', sa.Integer()),
    )
    for c in ('id', 'alert_id', 'detection_id', 'created_at', 'status'):
        op.create_index(f'ix_review_queue_{c}', 'review_queue', [c])


def downgrade() -> None:
    op.drop_table('review_queue')
    op.drop_table('model_versions')
    op.drop_table('dataset_items')
    op.drop_table('datasets')
