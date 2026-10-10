"""Add private web ingest jobs and admin mutation audit."""
from alembic import op
import sqlalchemy as sa

revision = 'c7e7a1d55a42'
down_revision = '93acb4e00651'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tracks', sa.Column('decommissioned_at', sa.DateTime(timezone=True)))
    op.create_table('audit_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='SET NULL')),
        sa.Column('action', sa.String(48), nullable=False),
        sa.Column('target_type', sa.String(32), nullable=False),
        sa.Column('target_id', sa.String(64)),
        sa.Column('summary', sa.String(240), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_audit_events_created_at', 'audit_events', ['created_at'])
    op.create_index('ix_audit_events_station_id', 'audit_events', ['station_id'])
    op.create_table('media_ingest_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='SET NULL')),
        sa.Column('error_code', sa.String(48)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','processing','accepted','duplicate','rejected','error')", name='ck_media_ingest_job_status'))
    op.create_index('ix_media_ingest_jobs_status', 'media_ingest_jobs', ['status'])
    op.create_index('ix_media_ingest_jobs_station_id', 'media_ingest_jobs', ['station_id'])


def downgrade():
    op.drop_table('media_ingest_jobs')
    op.drop_table('audit_events')
    op.drop_column('tracks', 'decommissioned_at')
