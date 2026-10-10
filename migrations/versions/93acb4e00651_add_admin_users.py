"""Add login-only admin identities; no public administration actions."""
from alembic import op
import sqlalchemy as sa

revision = '93acb4e00651'
down_revision = 'f2d3b66ece57'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('admin_users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('email', name='uq_admin_users_email'))


def downgrade():
    op.drop_table('admin_users')
