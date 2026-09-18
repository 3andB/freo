"""Durable station master broadcast requests."""
from alembic import op
import sqlalchemy as sa

revision = 'f19a73b206ce'
down_revision = 'e92b740a613f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('broadcast_revision', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('stations', sa.Column('broadcast_status', sa.String(16), nullable=False, server_default='ready'))
    op.add_column('stations', sa.Column('broadcast_error', sa.String(240), nullable=False, server_default=''))


def downgrade():
    for name in ('broadcast_error', 'broadcast_status', 'broadcast_revision'):
        op.drop_column('stations', name)
