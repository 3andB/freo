"""Optional provider credentials and station audio production."""
from alembic import op
import sqlalchemy as sa

revision = 'f806a1b2c3d4'
down_revision = 'f706a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('provider_credentials',
        sa.Column('provider', sa.String(24), primary_key=True),
        sa.Column('ciphertext', sa.Text()), sa.Column('model', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('station_production',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('script_provider', sa.String(24), nullable=False),
        sa.Column('voice_id', sa.String(120), nullable=False), sa.Column('model_id', sa.String(120), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False))
    op.create_table('production_grants',
        sa.Column('user_id', sa.Integer(), primary_key=True), sa.Column('station_id', sa.Integer(), primary_key=True),
        sa.Column('voice_tracking', sa.Boolean(), nullable=False), sa.Column('ai_generation', sa.Boolean(), nullable=False),
        sa.Column('playlists', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['user_id','station_id'], ['dj_station_assignments.admin_user_id','dj_station_assignments.station_id'], ondelete='CASCADE'))
    op.create_table('production_drafts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('creator_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('mode', sa.String(12), nullable=False), sa.Column('title', sa.String(200), nullable=False),
        sa.Column('subtype', sa.String(24), nullable=False), sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('components', sa.JSON(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False), sa.Column('error', sa.String(240)),
        sa.Column('ingest_job_id', sa.String(36), sa.ForeignKey('media_ingest_jobs.id', ondelete='SET NULL')),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_production_drafts_station_id','production_drafts',['station_id'])
    op.create_index('ix_production_drafts_updated_at','production_drafts',['updated_at'])
    op.create_table('production_attempts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('draft_id', sa.String(36), sa.ForeignKey('production_drafts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('request_id', sa.String(36), nullable=False), sa.Column('action', sa.String(24), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('inputs', sa.JSON(), nullable=False),
        sa.Column('provider', sa.String(24)), sa.Column('credential_revision', sa.Integer()),
        sa.Column('usage', sa.JSON(), nullable=False), sa.Column('error', sa.String(240)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('draft_id','request_id',name='uq_production_request'))
    op.create_index('ix_production_attempts_draft_id','production_attempts',['draft_id'])
    op.create_index('ix_production_attempts_status','production_attempts',['status'])


def downgrade():
    for name in ('production_attempts','production_drafts','production_grants','station_production','provider_credentials'):
        op.drop_table(name)
