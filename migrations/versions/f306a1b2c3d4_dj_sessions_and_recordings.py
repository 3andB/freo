"""Station DJ assignments, confirmed show history and opt-in recordings."""
from alembic import op
import sqlalchemy as sa

revision = 'f306a1b2c3d4'
down_revision = 'f206a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('admin_users') as batch:
        batch.add_column(sa.Column('role', sa.String(8), nullable=False, server_default='ADMIN'))
        batch.create_check_constraint('ck_admin_user_role', "role IN ('ADMIN','DJ')")
    op.create_table('dj_station_assignments',
        sa.Column('admin_user_id', sa.Integer, sa.ForeignKey('admin_users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('station_id', sa.Integer, sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True))
    op.create_table('live_sessions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('station_id', sa.Integer, sa.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('active_station_id', sa.Integer, sa.ForeignKey('stations.id', ondelete='RESTRICT'), unique=True),
        sa.Column('admin_user_id', sa.Integer, sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('dj_name', sa.String(254), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('end_reason', sa.String(80)),
        sa.Column('end_requested', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('record_requested', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('engine_identity', sa.String(64)))
    op.create_index('ix_live_sessions_station_id', 'live_sessions', ['station_id'])
    op.create_table('show_recordings',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('session_id', sa.String(32), sa.ForeignKey('live_sessions.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('station_id', sa.Integer, sa.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('admin_user_id', sa.Integer, sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('storage_key', sa.String(50), nullable=False, unique=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('duration_ms', sa.Integer),
        sa.Column('file_size_bytes', sa.BigInteger),
        sa.Column('error', sa.String(160)),
        sa.CheckConstraint("status IN ('pending','recording','finalizing','complete','partial','failed')", name='ck_show_recording_status'))
    op.create_index('ix_show_recordings_station_id', 'show_recordings', ['station_id'])
    op.add_column('live_queue_snapshots', sa.Column('show_observation', sa.JSON))


def downgrade():
    with op.batch_alter_table('live_queue_snapshots') as batch:
        batch.drop_column('show_observation')
    op.drop_table('show_recordings')
    op.drop_table('live_sessions')
    op.drop_table('dj_station_assignments')
    with op.batch_alter_table('admin_users') as batch:
        batch.drop_constraint('ck_admin_user_role', type_='check')
        batch.drop_column('role')
