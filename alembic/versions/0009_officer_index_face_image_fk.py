"""index on camera_officers.id and the face_encodings.image_id foreign key the models declare

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

FK = 'fk_face_encodings_image_id_person_images'


def upgrade() -> None:
    op.create_index(op.f('ix_camera_officers_id'), 'camera_officers', ['id'], unique=False)
    # Batch mode: SQLite cannot add a foreign key with ALTER TABLE, so the table is copied.
    with op.batch_alter_table('face_encodings') as batch:
        batch.create_foreign_key(FK, 'person_images', ['image_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('face_encodings') as batch:
        batch.drop_constraint(FK, type_='foreignkey')
    op.drop_index(op.f('ix_camera_officers_id'), table_name='camera_officers')
