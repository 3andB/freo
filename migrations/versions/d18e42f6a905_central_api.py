"""Permanent station identity and private central API reporting state.

Revision ID: d18e42f6a905
Revises: c07d9a21b634
"""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = 'd18e42f6a905'
down_revision = 'c07d9a21b634'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('freo_station_id', sa.String(36)))
    # Application-generated UUIDs avoid requiring a PostgreSQL extension.
    connection = op.get_bind()
    for station_id in connection.execute(sa.text('SELECT id FROM stations')).scalars():
        connection.execute(sa.text('UPDATE stations SET freo_station_id = :uuid WHERE id = :id'),
                           {'uuid': str(uuid4()), 'id': station_id})
    with op.batch_alter_table('stations') as batch:
        batch.alter_column('freo_station_id', existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint('uq_stations_freo_station_id', ['freo_station_id'])
        batch.add_column(sa.Column('country', sa.String(2), nullable=False, server_default=''))
        batch.add_column(sa.Column('genre', sa.String(100), nullable=False, server_default=''))
        batch.add_column(sa.Column('directory_categories', sa.JSON(), nullable=False, server_default='[]'))
        batch.add_column(sa.Column('directory_opt_in', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('central_installation',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('manager_email', sa.String(254), nullable=False),
        sa.Column('installation_id', sa.String(36)),
        sa.Column('registration_state', sa.String(24), nullable=False),
        sa.Column('license_cache', sa.JSON()), sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('last_error', sa.String(64), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_central_installation_singleton'))
    op.create_table('central_station_state',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('last_sample', sa.JSON()), sa.Column('synced_digest', sa.String(64)))
    op.create_table('central_hourly_metrics',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('period_start', sa.BigInteger(), primary_key=True),
        sa.Column('observed_seconds', sa.Float(), nullable=False),
        sa.Column('listener_seconds', sa.Float(), nullable=False),
        sa.Column('peak_listeners', sa.BigInteger(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('sent', sa.Boolean(), nullable=False))
    op.create_index('ix_central_hourly_metrics_period_start', 'central_hourly_metrics', ['period_start'])


def downgrade():
    op.drop_table('central_hourly_metrics')
    op.drop_table('central_station_state')
    op.drop_table('central_installation')
    with op.batch_alter_table('stations') as batch:
        batch.drop_constraint('uq_stations_freo_station_id', type_='unique')
        for name in ('directory_opt_in', 'directory_categories', 'genre', 'country', 'freo_station_id'):
            batch.drop_column(name)
