"""Public player settings, published schedules, and listener feedback."""
from alembic import op
import sqlalchemy as sa

revision = 'f84c1d92be30'
down_revision = 'f73b8c9012ab'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('station_player_settings',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('config', sa.JSON(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False))
    op.create_table('station_player_assets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False), sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('version', sa.String(64), nullable=False), sa.UniqueConstraint('station_id','kind',name='uq_player_asset'))
    op.create_table('public_schedule_revisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entries', sa.JSON(), nullable=False), sa.Column('config_revision', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False), sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_public_schedule_revisions_station_id','public_schedule_revisions',['station_id'])
    op.create_table('listener_votes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('listener_key', sa.String(64), nullable=False), sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=False), sa.Column('comment', sa.String(500), nullable=False),
        sa.Column('review_state', sa.String(12), nullable=False), sa.Column('excluded', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('station_id','track_id','listener_key',name='uq_listener_song_vote'),
        sa.CheckConstraint('value IN (-1,0,1)',name='ck_listener_vote_value'))
    op.create_index('ix_listener_votes_station_id','listener_votes',['station_id'])
    op.create_table('listener_feedback_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('listener_key', sa.String(64), nullable=False), sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(40), nullable=False), sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('station_id','listener_key','created_at'):
        op.create_index('ix_listener_feedback_events_'+column,'listener_feedback_events',[column])


def downgrade():
    for table in ('listener_feedback_events','listener_votes','public_schedule_revisions','station_player_assets','station_player_settings'):
        op.drop_table(table)
