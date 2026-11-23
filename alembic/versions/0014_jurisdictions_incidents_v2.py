"""jurisdictions, officer profiles, incident v2 (status machine, assignments, typed timeline),
camera jurisdiction, append-only hash-chained audit log

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jurisdictions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name_en', sa.String(length=100), nullable=False),
        sa.Column('name_bn', sa.String(length=100), nullable=True),
        sa.Column('level', sa.String(length=12), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('geojson', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['jurisdictions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_jurisdictions_id', 'jurisdictions', ['id'])
    op.create_index('ix_jurisdictions_code', 'jurisdictions', ['code'], unique=True)
    op.create_index('ix_jurisdictions_level', 'jurisdictions', ['level'])
    op.create_index('ix_jurisdictions_parent_id', 'jurisdictions', ['parent_id'])

    op.create_table(
        'officer_profiles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=True),
        sa.Column('rank', sa.String(length=40), nullable=True),
        sa.Column('badge_no', sa.String(length=30), nullable=True),
        sa.Column('station_id', sa.Integer(), nullable=True),
        sa.Column('duty_status', sa.String(length=12), server_default='off_duty', nullable=False),
        sa.Column('photo', sa.LargeBinary(), nullable=True),
        sa.Column('photo_type', sa.String(length=30), nullable=True),
        sa.Column('last_lat', sa.Float(), nullable=True),
        sa.Column('last_lng', sa.Float(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['station_id'], ['jurisdictions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_index('ix_officer_profiles_badge_no', 'officer_profiles', ['badge_no'], unique=True)
    op.create_index('ix_officer_profiles_duty_status', 'officer_profiles', ['duty_status'])

    op.create_table(
        'officer_jurisdictions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('jurisdiction_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['jurisdiction_id'], ['jurisdictions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'jurisdiction_id', name='uq_officer_jurisdiction'),
    )
    op.create_index('ix_officer_jurisdictions_user_id', 'officer_jurisdictions', ['user_id'])
    op.create_index('ix_officer_jurisdictions_jurisdiction_id', 'officer_jurisdictions', ['jurisdiction_id'])

    op.create_table(
        'incident_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(length=14), server_default='assigned', nullable=False),
        sa.Column('out_of_area', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_incident_assignments_id', 'incident_assignments', ['id'])
    op.create_index('ix_incident_assignments_incident_id', 'incident_assignments', ['incident_id'])
    op.create_index('ix_incident_assignments_user_id', 'incident_assignments', ['user_id'])
    op.create_index('uq_incident_assignment', 'incident_assignments', ['incident_id', 'user_id'], unique=True)

    with op.batch_alter_table('incidents') as b:
        b.add_column(sa.Column('source', sa.String(length=20), server_default='alert', nullable=False))
        b.add_column(sa.Column('jurisdiction_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('watchlist_person_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('watchlist_vehicle_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('cross_track_id', sa.Integer(), nullable=True))
        b.create_index('ix_incidents_jurisdiction_id', ['jurisdiction_id'])
        b.create_index('ix_incidents_watchlist_person_id', ['watchlist_person_id'])
        b.create_index('ix_incidents_watchlist_vehicle_id', ['watchlist_vehicle_id'])
        b.create_index('ix_incidents_cross_track_id', ['cross_track_id'])
        b.create_foreign_key('fk_incidents_jurisdiction', 'jurisdictions', ['jurisdiction_id'], ['id'], ondelete='SET NULL')
    # v2 status machine: open → new, investigating → in_progress
    op.execute("UPDATE incidents SET status = 'new' WHERE status = 'open'")
    op.execute("UPDATE incidents SET status = 'in_progress' WHERE status = 'investigating'")
    # Back-fill one assignment row per existing primary assignee.
    op.execute("INSERT INTO incident_assignments (incident_id, user_id, state, out_of_area) "
               "SELECT id, assigned_to, 'assigned', false FROM incidents WHERE assigned_to IS NOT NULL")

    with op.batch_alter_table('incident_events') as b:
        b.add_column(sa.Column('actor_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('camera_id', sa.String(length=50), nullable=True))
        b.add_column(sa.Column('payload', sa.Text(), nullable=True))

    with op.batch_alter_table('cameras') as b:
        b.add_column(sa.Column('jurisdiction_id', sa.Integer(), nullable=True))
        b.create_index('ix_cameras_jurisdiction_id', ['jurisdiction_id'])

    with op.batch_alter_table('audit_logs') as b:
        b.add_column(sa.Column('prev_hash', sa.String(length=64), nullable=True))
        b.add_column(sa.Column('record_hash', sa.String(length=64), nullable=True))
        b.create_index('ix_audit_logs_record_hash', ['record_hash'])

    if op.get_bind().dialect.name == 'postgresql':
        # Append-only at the database too: no UPDATE / DELETE of audit rows, from any client.
        op.execute("""
            CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END; $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER audit_logs_no_change BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_change ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    with op.batch_alter_table('audit_logs') as b:
        b.drop_index('ix_audit_logs_record_hash')
        b.drop_column('record_hash')
        b.drop_column('prev_hash')
    with op.batch_alter_table('cameras') as b:
        b.drop_index('ix_cameras_jurisdiction_id')
        b.drop_column('jurisdiction_id')
    with op.batch_alter_table('incident_events') as b:
        b.drop_column('payload')
        b.drop_column('camera_id')
        b.drop_column('actor_id')
    op.execute("UPDATE incidents SET status = 'open' WHERE status IN ('new', 'acknowledged', 'verified_match')")
    op.execute("UPDATE incidents SET status = 'investigating' WHERE status IN "
               "('in_progress', 'officer_dispatched', 'target_located')")
    op.execute("UPDATE incidents SET status = 'closed' WHERE status = 'false_alarm'")
    with op.batch_alter_table('incidents') as b:
        b.drop_constraint('fk_incidents_jurisdiction', type_='foreignkey')
        for ix in ('ix_incidents_cross_track_id', 'ix_incidents_watchlist_vehicle_id',
                   'ix_incidents_watchlist_person_id', 'ix_incidents_jurisdiction_id'):
            b.drop_index(ix)
        for col in ('cross_track_id', 'watchlist_vehicle_id', 'watchlist_person_id', 'jurisdiction_id', 'source'):
            b.drop_column(col)
    op.drop_table('incident_assignments')
    op.drop_table('officer_jurisdictions')
    op.drop_table('officer_profiles')
    op.drop_table('jurisdictions')
