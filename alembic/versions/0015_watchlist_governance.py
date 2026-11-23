"""watchlist governance (people), vehicle watchlist, vehicle catalog

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-23

Legacy criminal entries and watchlisted plates are adopted at app start-up
(backend/services/watchlist_gov.adopt_legacy): active for 30 days, flagged needs_review.
"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

PERSON_COLS = [
    ('aliases', sa.Text()), ('case_no', sa.String(60)), ('offence', sa.String(120)), ('risk_level', sa.String(10)),
    ('issuing_authority', sa.String(120)), ('legal_basis', sa.Text()), ('wl_status', sa.String(12)),
    ('requested_by', sa.Integer()), ('requested_at', sa.DateTime(timezone=True)), ('approved_by', sa.Integer()),
    ('approved_at', sa.DateTime(timezone=True)), ('starts_at', sa.DateTime(timezone=True)),
    ('expires_at', sa.DateTime(timezone=True)), ('decision_note', sa.Text()),
]


def upgrade() -> None:
    with op.batch_alter_table('known_persons') as b:
        for name, typ in PERSON_COLS:
            b.add_column(sa.Column(name, typ, nullable=True))
        b.add_column(sa.Column('needs_review', sa.Boolean(), server_default=sa.false(), nullable=False))
        b.create_index('ix_known_persons_case_no', ['case_no'])
        b.create_index('ix_known_persons_wl_status', ['wl_status'])
        b.create_index('ix_known_persons_expires_at', ['expires_at'])

    op.create_table(
        'watchlist_vehicles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ref', sa.String(20), nullable=False),
        sa.Column('plate_raw', sa.String(60)), sa.Column('plate_canonical', sa.String(60)),
        sa.Column('vehicle_type', sa.String(30)), sa.Column('color_primary', sa.String(20)),
        sa.Column('color_secondary', sa.String(20)), sa.Column('make_model', sa.String(60)),
        sa.Column('marks', sa.Text()), sa.Column('notes', sa.Text()),
        sa.Column('linked_person_id', sa.Integer(), sa.ForeignKey('known_persons.id', ondelete='SET NULL')),
        sa.Column('risk_level', sa.String(10), nullable=False, server_default='medium'),
        sa.Column('case_no', sa.String(60), nullable=False), sa.Column('offence', sa.String(120)),
        sa.Column('issuing_authority', sa.String(120), nullable=False), sa.Column('legal_basis', sa.Text(), nullable=False),
        sa.Column('wl_status', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('requested_by', sa.Integer()), sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('approved_by', sa.Integer()), sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decision_note', sa.Text()),
        sa.Column('needs_review', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
    for col, unique in (('id', False), ('ref', True), ('plate_canonical', False), ('vehicle_type', False),
                        ('color_primary', False), ('make_model', False), ('case_no', False), ('wl_status', False),
                        ('expires_at', False)):
        op.create_index(f'ix_watchlist_vehicles_{col}', 'watchlist_vehicles', [col], unique=unique)

    op.create_table(
        'watchlist_vehicle_photos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('watchlist_vehicles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('encrypted', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('content_type', sa.String(30), nullable=False, server_default='image/jpeg'),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('embedding', sa.LargeBinary()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_watchlist_vehicle_photos_id', 'watchlist_vehicle_photos', ['id'])
    op.create_index('ix_watchlist_vehicle_photos_vehicle_id', 'watchlist_vehicle_photos', ['vehicle_id'])
    op.create_index('ix_watchlist_vehicle_photos_sha256', 'watchlist_vehicle_photos', ['sha256'])

    op.create_table(
        'vehicle_catalog',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('code', sa.String(40), nullable=False),
        sa.Column('name_en', sa.String(60), nullable=False), sa.Column('name_bn', sa.String(60)),
        sa.Column('parent_code', sa.String(40)),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
        sa.UniqueConstraint('kind', 'code', name='uq_vehicle_catalog'),
    )
    op.create_index('ix_vehicle_catalog_id', 'vehicle_catalog', ['id'])
    op.create_index('ix_vehicle_catalog_kind', 'vehicle_catalog', ['kind'])


def downgrade() -> None:
    op.drop_table('vehicle_catalog')
    op.drop_table('watchlist_vehicle_photos')
    op.drop_table('watchlist_vehicles')
    with op.batch_alter_table('known_persons') as b:
        for ix in ('ix_known_persons_expires_at', 'ix_known_persons_wl_status', 'ix_known_persons_case_no'):
            b.drop_index(ix)
        b.drop_column('needs_review')
        for name, _ in reversed(PERSON_COLS):
            b.drop_column(name)
