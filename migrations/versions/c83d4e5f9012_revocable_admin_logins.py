"""Make each existing signed-cookie login independently revocable."""
from alembic import op
import sqlalchemy as sa

revision = 'c83d4e5f9012'
down_revision = 'b72e19d4c603'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('admin_login_sessions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_admin_login_sessions_expires_at', 'admin_login_sessions', ['expires_at'])


def downgrade():
    raise RuntimeError('Login revocation must not be removed in place; use a matched recovery point.')
