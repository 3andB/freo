"""Editable public station identity and bounded calendar programs."""
from alembic import op
import sqlalchemy as sa
revision = 'f35a908ed421'
down_revision = 'e91b6c8a02f3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('stations') as batch:
        batch.add_column(sa.Column('public_slug', sa.String(64)))
        batch.create_unique_constraint('uq_stations_public_slug', ['public_slug'])
    op.create_table('station_aliases', sa.Column('slug', sa.String(64), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False))
    op.create_table('schedule_programs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('on_date', sa.Date()), sa.Column('start_minute', sa.Integer(), nullable=False),
        sa.Column('end_minute', sa.Integer(), nullable=False),
        sa.Column('clock_id', sa.Integer(), sa.ForeignKey('clocks.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('weekday BETWEEN 0 AND 6 AND start_minute BETWEEN 0 AND 1439 AND end_minute BETWEEN 1 AND 2880 AND end_minute > start_minute AND end_minute - start_minute <= 1440', name='ck_program_window'))


def downgrade():
    op.drop_table('schedule_programs')
    op.drop_table('station_aliases')
    with op.batch_alter_table('stations') as batch:
        batch.drop_constraint('uq_stations_public_slug', type_='unique')
        batch.drop_column('public_slug')
