"""Verified station custom domains."""
from alembic import op
import sqlalchemy as sa

revision = 'a09f6d3e82b1'
down_revision = 'c48f1d207ab9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('station_domains',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hostname', sa.String(253), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('verification_token', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('hostname', name='uq_station_domains_hostname'),
        sa.CheckConstraint('NOT enabled OR verified_at IS NOT NULL', name='ck_station_domains_verified'),
        sa.CheckConstraint('NOT is_primary OR enabled', name='ck_station_domains_primary_enabled'))
    op.create_index('ix_station_domains_station_id', 'station_domains', ['station_id'])
    op.create_index('uq_station_domains_primary', 'station_domains', ['station_id'], unique=True,
                    postgresql_where=sa.text('is_primary'), sqlite_where=sa.text('is_primary = 1'))


def downgrade():
    op.drop_table('station_domains')
