"""Managed station upstream relay configuration and safe observations."""
from alembic import op
import sqlalchemy as sa

revision = 'f706a1b2c3d4'
down_revision = 'f606a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('station_relays',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('url', sa.String(2048), nullable=False, server_default=''),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('applied_revision', sa.Integer()),
        sa.Column('observation', sa.JSON()),
        sa.Column('observed_at', sa.DateTime(timezone=True)),
        sa.Column('last_failure_at', sa.DateTime(timezone=True)),
        sa.Column('last_reconnect_at', sa.DateTime(timezone=True)),
        sa.Column('error', sa.String(160)))


def downgrade():
    op.drop_table('station_relays')
