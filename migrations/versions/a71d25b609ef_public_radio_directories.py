"""Opt-in public radio directories, independent of the Freo directory."""
from alembic import op
import sqlalchemy as sa

revision = 'a71d25b609ef'
down_revision = 'f38c6a902e17'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('radio_browser_uuid', sa.String(36)))
    op.add_column('stations', sa.Column('radio_browser_status', sa.String(16), nullable=False, server_default='not_listed'))
    op.add_column('stations', sa.Column('radio_browser_error', sa.String(240), nullable=False, server_default=''))
    op.add_column('stations', sa.Column('internet_radio_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('stations', sa.Column('internet_radio_pending', sa.Boolean()))
    op.add_column('stations', sa.Column('internet_radio_status', sa.String(16), nullable=False, server_default='ready'))
    op.add_column('stations', sa.Column('internet_radio_error', sa.String(240), nullable=False, server_default=''))


def downgrade():
    for name in ('internet_radio_error', 'internet_radio_status', 'internet_radio_pending',
                 'internet_radio_enabled', 'radio_browser_error', 'radio_browser_status', 'radio_browser_uuid'):
        op.drop_column('stations', name)
