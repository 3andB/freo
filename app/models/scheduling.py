"""Revisioned visual schedules and worker-owned mode transitions."""
from datetime import datetime, timezone
from app.extensions import db


def now():
    return datetime.now(timezone.utc)


class ChannelSchedule(db.Model):
    __tablename__ = 'channel_schedules'
    __table_args__ = (db.CheckConstraint("mode IN ('CALENDAR','BLOCKS','SIMPLE')", name='ck_channel_schedule_mode'),)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    mode = db.Column(db.String(12), nullable=False, default='CALENDAR')
    activated = db.Column(db.Boolean, nullable=False, default=False)
    activation = db.Column(db.String(36), nullable=False, default='initial')
    revision = db.Column(db.Integer, nullable=False, default=1)
    calendar = db.Column(db.JSON, nullable=False, default=list)
    assignments = db.Column(db.JSON, nullable=False, default=list)
    simple = db.Column(db.JSON)
    live_simple = db.Column(db.JSON)
    revision_updates = db.Column(db.JSON, nullable=False, default=list)
    calendar_saved = db.Column(db.Boolean, nullable=False, default=False)
    default_playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id', ondelete='RESTRICT'))
    station = db.relationship('Station', backref=db.backref('scheduling', uselist=False))
    default_playlist = db.relationship('Playlist')


class ScheduleComposition(db.Model):
    __tablename__ = 'schedule_compositions'
    __table_args__ = (db.CheckConstraint("kind IN ('SHOW','BLOCK')", name='ck_composition_kind'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(8), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    revision = db.Column(db.Integer, nullable=False, default=1)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    versions = db.relationship('ScheduleCompositionRevision', back_populates='composition', order_by='ScheduleCompositionRevision.version')


class ScheduleCompositionRevision(db.Model):
    __tablename__ = 'schedule_composition_revisions'
    __table_args__ = (db.UniqueConstraint('composition_id', 'version', name='uq_composition_revision'),)
    id = db.Column(db.Integer, primary_key=True)
    composition_id = db.Column(db.Integer, db.ForeignKey('schedule_compositions.id', ondelete='CASCADE'), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # seconds
    sections = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    composition = db.relationship('ScheduleComposition', back_populates='versions')


class ScheduleTransition(db.Model):
    __tablename__ = 'schedule_transitions'
    id = db.Column(db.String(36), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    mode = db.Column(db.String(12), nullable=False)
    previous_mode = db.Column(db.String(12), nullable=False)
    simple = db.Column(db.JSON)
    revision = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(16), nullable=False, default='PENDING')
    decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    interrupted_ids = db.Column(db.JSON, nullable=False, default=list)
    error = db.Column(db.String(200))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    completed_at = db.Column(db.DateTime(timezone=True))
    decision = db.relationship('SelectionDecision')


class ScheduleCursor(db.Model):
    __tablename__ = 'schedule_cursors'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    key = db.Column(db.String(200), primary_key=True)
    state = db.Column(db.JSON, nullable=False, default=dict)
