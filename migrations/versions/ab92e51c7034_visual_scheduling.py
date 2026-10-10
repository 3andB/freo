"""Revisioned Shows, three scheduling modes, and hourly Events.

Revision ID: ab92e51c7034
Revises: d18e42f6a905
"""
from alembic import op
import sqlalchemy as sa

revision = 'ab92e51c7034'
down_revision = 'd18e42f6a905'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_tracks_title_id','tracks',['title','id'])
    op.create_table('channel_schedules',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mode', sa.String(12), nullable=False), sa.Column('activated', sa.Boolean(), nullable=False),
        sa.Column('activation', sa.String(36), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('calendar', sa.JSON(), nullable=False), sa.Column('assignments', sa.JSON(), nullable=False),
        sa.Column('simple', sa.JSON()), sa.Column('live_simple', sa.JSON()), sa.Column('revision_updates', sa.JSON(), nullable=False), sa.Column('calendar_saved', sa.Boolean(), nullable=False), sa.Column('default_playlist_id', sa.Integer(), sa.ForeignKey('playlists.id', ondelete='RESTRICT')),
        sa.CheckConstraint("mode IN ('CALENDAR','BLOCKS','SIMPLE')", name='ck_channel_schedule_mode'))
    op.create_table('schedule_compositions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False), sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.String(500), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('archived', sa.Boolean(), nullable=False),
        sa.CheckConstraint("kind IN ('SHOW','BLOCK')", name='ck_composition_kind'))
    op.create_index('ix_schedule_compositions_station_id', 'schedule_compositions', ['station_id'])
    op.create_table('schedule_composition_revisions',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('composition_id', sa.Integer(), sa.ForeignKey('schedule_compositions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('sections', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('composition_id', 'version', name='uq_composition_revision'))
    op.create_index('ix_schedule_composition_revisions_composition_id', 'schedule_composition_revisions', ['composition_id'])
    op.create_table('schedule_transitions',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mode', sa.String(12), nullable=False), sa.Column('previous_mode', sa.String(12), nullable=False),
        sa.Column('simple', sa.JSON()), sa.Column('revision', sa.Integer(), nullable=False), sa.Column('state', sa.String(16), nullable=False),
        sa.Column('decision_id', sa.Integer(), sa.ForeignKey('selection_decisions.id', ondelete='SET NULL')),
        sa.Column('interrupted_ids', sa.JSON(), nullable=False), sa.Column('error', sa.String(200)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('completed_at', sa.DateTime(timezone=True)))
    op.create_index('ix_schedule_transitions_station_id', 'schedule_transitions', ['station_id'])
    op.create_table('schedule_cursors',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('key', sa.String(200), primary_key=True), sa.Column('state', sa.JSON(), nullable=False))
    op.add_column('timed_events', sa.Column('repeat_hours', sa.JSON()))
    op.add_column('timed_events', sa.Column('starts_on', sa.Date()))
    op.add_column('timed_events', sa.Column('ends_on', sa.Date()))


def downgrade():
    op.drop_index('ix_tracks_title_id',table_name='tracks')
    for name in ('ends_on', 'starts_on', 'repeat_hours'):
        op.drop_column('timed_events', name)
    for name in ('schedule_cursors', 'schedule_transitions', 'schedule_composition_revisions', 'schedule_compositions', 'channel_schedules'):
        op.drop_table(name)
