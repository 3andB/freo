"""Installation administration, offline licenses and approved upgrade requests."""
from alembic import op
import sqlalchemy as sa

revision = 'e83b9204c6af'
down_revision = 'd02f9a41c830'
branch_labels = None
depends_on = None


def upgrade():
    # Existing account values remain untouched. Grant the new privilege through
    # the root CLI after adoption; the first account on a fresh install receives it.
    op.add_column('admin_users', sa.Column('installation_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('software_license', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document', sa.JSON(), nullable=False), sa.CheckConstraint('id = 1', name='ck_software_license_singleton'))
    op.create_table('system_upgrades', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('version', sa.String(64), nullable=False), sa.Column('state', sa.String(24), nullable=False),
        sa.Column('message', sa.String(500), nullable=False, server_default=''),
        sa.Column('requested_by', sa.Integer(), sa.ForeignKey('admin_users.id')))


def downgrade():
    raise RuntimeError('Distribution controls contain durable state; use a matched recovery point.')
