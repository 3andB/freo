"""Add exact-time event definitions and durable occurrences.

Revision ID: b7e14f9c203d
Revises: 8d62c4a9b10e
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7e14f9c203d'
down_revision = '8d62c4a9b10e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('timed_events',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('uuid', sa.String(36), nullable=False, unique=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('description', sa.String(500), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('timing_mode', sa.String(20), nullable=False),
        sa.Column('content_type', sa.String(20), nullable=False),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='RESTRICT')),
        sa.Column('imaging_asset_id', sa.Integer(), sa.ForeignKey('imaging_assets.id', ondelete='RESTRICT')),
        sa.Column('recurrence_type', sa.String(12), nullable=False), sa.Column('scheduled_at_utc', sa.DateTime(timezone=True)),
        sa.Column('weekday', sa.Integer()), sa.Column('local_time', sa.Time()),
        sa.Column('early_tolerance_seconds', sa.Integer(), nullable=False), sa.Column('late_tolerance_seconds', sa.Integer(), nullable=False),
        sa.Column('missed_policy', sa.String(12), nullable=False), sa.Column('interrupt_policy', sa.String(16), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("timing_mode IN ('SOFT','HARD','NON_INTERRUPTING')", name='ck_timed_event_mode'),
        sa.CheckConstraint("recurrence_type IN ('ONE_TIME','WEEKLY')", name='ck_timed_event_recurrence'),
        sa.CheckConstraint("content_type IN ('TRACK','IMAGING_ASSET')", name='ck_timed_event_content_type'),
        sa.CheckConstraint("missed_policy IN ('SKIP','PLAY_LATE')", name='ck_timed_event_missed'),
        sa.CheckConstraint("interrupt_policy IN ('NEVER','MUSIC_ONLY')", name='ck_timed_event_interrupt'),
        sa.CheckConstraint("(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL)", name='ck_timed_event_content'),
        sa.CheckConstraint("(recurrence_type='ONE_TIME' AND scheduled_at_utc IS NOT NULL AND weekday IS NULL AND local_time IS NULL) OR (recurrence_type='WEEKLY' AND scheduled_at_utc IS NULL AND weekday BETWEEN 0 AND 6 AND local_time IS NOT NULL)", name='ck_timed_event_schedule'),
        sa.CheckConstraint('early_tolerance_seconds BETWEEN 0 AND 3600 AND late_tolerance_seconds BETWEEN 1 AND 86400', name='ck_timed_event_window'))
    op.create_index('ix_timed_events_uuid', 'timed_events', ['uuid'], unique=True)
    op.create_index('ix_timed_events_station_id', 'timed_events', ['station_id'])
    op.create_table('timed_event_occurrences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('timed_event_id', sa.Integer(), sa.ForeignKey('timed_events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_for_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('eligible_at_utc', sa.DateTime(timezone=True), nullable=False), sa.Column('deadline_at_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(12), nullable=False),
        sa.Column('selection_decision_id', sa.Integer(), sa.ForeignKey('selection_decisions.id', ondelete='SET NULL'), unique=True),
        sa.Column('queued_at', sa.DateTime(timezone=True)), sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('missed_at', sa.DateTime(timezone=True)), sa.Column('failure_reason', sa.String(80)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('timed_event_id', 'scheduled_for_utc', name='uq_timed_occurrence_instant'),
        sa.CheckConstraint("state IN ('PENDING','READY','QUEUED','STARTED','MISSED','FAILED','CANCELLED')", name='ck_timed_occurrence_state'))
    for column in ('timed_event_id','station_id','scheduled_for_utc','state'):
        op.create_index('ix_timed_event_occurrences_'+column, 'timed_event_occurrences', [column])


def downgrade():
    op.drop_table('timed_event_occurrences')
    op.drop_table('timed_events')
