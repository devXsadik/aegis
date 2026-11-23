"""people in case evidence, with clothing colours (search inside a case)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'evidence_persons',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('evidence_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('incident_id', sa.Integer(), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('t_seconds', sa.Float()),
        sa.Column('bbox', sa.String(60), nullable=False),
        sa.Column('upper_color', sa.String(12)),
        sa.Column('lower_color', sa.String(12)),
        sa.Column('crop', sa.LargeBinary()),
        sa.Column('crop_encrypted', sa.Boolean(), nullable=False, server_default='0'),
    )
    for col in ('id', 'item_id', 'incident_id', 'upper_color', 'lower_color'):
        op.create_index(f'ix_evidence_persons_{col}', 'evidence_persons', [col])


def downgrade() -> None:
    op.drop_table('evidence_persons')
