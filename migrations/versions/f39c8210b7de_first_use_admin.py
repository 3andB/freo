"""First-use administrator setup state; no account creation on upgrade."""
from alembic import op
import sqlalchemy as sa
revision = 'f39c8210b7de'
down_revision = 'e83b9204c6af'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_users', sa.Column('username', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_admin_users_username', 'admin_users', ['username'])
    op.add_column('admin_users', sa.Column('setup_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('admin_bootstrap', sa.Column('id', sa.Integer(), primary_key=True),
        sa.CheckConstraint('id = 1', name='ck_admin_bootstrap_singleton'))


def downgrade():
    raise RuntimeError('Administrator setup is durable state; use a matched recovery point.')
