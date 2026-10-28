"""Recording display names and durable, audited file deletion requests."""
from alembic import op
import sqlalchemy as sa

revision = 'f316a1b2c3d4'
down_revision = 'f306a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('show_recordings') as batch:
        batch.add_column(sa.Column('name', sa.String(160), nullable=False, server_default=''))
        batch.add_column(sa.Column('revision', sa.Integer, nullable=False, server_default='0'))
        batch.add_column(sa.Column('deletion_requested_at', sa.DateTime(timezone=True)))
        batch.add_column(sa.Column('deletion_requested_by', sa.Integer))
        batch.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True)))
        batch.add_column(sa.Column('deletion_error', sa.String(160)))
        batch.create_foreign_key('fk_recording_deletion_user', 'admin_users', ['deletion_requested_by'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('show_recordings') as batch:
        batch.drop_constraint('fk_recording_deletion_user', type_='foreignkey')
        for column in ('deletion_error', 'deleted_at', 'deletion_requested_by', 'deletion_requested_at', 'revision', 'name'):
            batch.drop_column(column)
