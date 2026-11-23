"""incident messages, officer shifts, district scope on users

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'incident_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('incident_id', sa.Integer(), sa.ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('author_name', sa.String(100), nullable=False),
        sa.Column('author_role', sa.String(20), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('evidence_ref', sa.String(40)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_incident_messages_id', 'incident_messages', ['id'])
    op.create_index('ix_incident_messages_incident_id', 'incident_messages', ['incident_id'])
    op.create_index('ix_incident_messages_created_at', 'incident_messages', ['created_at'])
    op.create_table(
        'officer_shifts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('jurisdiction_id', sa.Integer(), sa.ForeignKey('jurisdictions.id', ondelete='SET NULL')),
        sa.Column('assignment', sa.String(80)),
        sa.Column('created_by', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    for col in ('id', 'user_id', 'starts_at', 'ends_at', 'jurisdiction_id'):
        op.create_index(f'ix_officer_shifts_{col}', 'officer_shifts', [col])
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('scope_jurisdiction_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_users_scope_jurisdiction', 'jurisdictions', ['scope_jurisdiction_id'], ['id'], ondelete='SET NULL')
        b.create_index('ix_users_scope_jurisdiction_id', ['scope_jurisdiction_id'])


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.drop_index('ix_users_scope_jurisdiction_id')
        b.drop_constraint('fk_users_scope_jurisdiction', type_='foreignkey')
        b.drop_column('scope_jurisdiction_id')
    op.drop_table('officer_shifts')
    op.drop_table('incident_messages')
