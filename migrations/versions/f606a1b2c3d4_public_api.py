"""Revocable, station-scoped public API credentials and shared rate limits."""
from alembic import op
import sqlalchemy as sa

revision = 'f606a1b2c3d4'
down_revision = 'f506a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('api_credentials',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('token_digest', sa.String(64), nullable=False),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("scope = 'read'", name='ck_api_credential_scope'))
    op.create_table('api_credential_stations',
        sa.Column('credential_id', sa.String(32), sa.ForeignKey('api_credentials.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True))
    op.create_table('api_rate_buckets',
        sa.Column('kind', sa.String(16), primary_key=True),
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('minute', sa.BigInteger(), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False))
    op.create_index('ix_api_rate_buckets_minute', 'api_rate_buckets', ['minute'])


def downgrade():
    op.drop_table('api_rate_buckets')
    op.drop_table('api_credential_stations')
    op.drop_table('api_credentials')
