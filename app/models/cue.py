"""Durable booth drafts, saved sets, and exactly-once playback rotation."""
from datetime import datetime, timezone
import uuid

from app.extensions import db


class BoothCue(db.Model):
    __tablename__ = 'booth_cues'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    revision = db.Column(db.Integer, nullable=False, default=1)
    generation = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False, default='Untitled Cue')
    entries = db.Column(db.JSON, nullable=False, default=list)
    saved_id = db.Column(db.Integer)
    saved_order = db.Column(db.JSON, nullable=False, default=list)
    auto_enabled = db.Column(db.Boolean, nullable=False, default=False)
    start_pending = db.Column(db.Boolean, nullable=False, default=False)
    last_deck = db.Column(db.String(1), nullable=False, default='A')
    message = db.Column(db.String(240), nullable=False, default='')


class SavedBoothCue(db.Model):
    __tablename__ = 'saved_booth_cues'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    tracks = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CuePlayback(db.Model):
    __tablename__ = 'cue_playbacks'
    decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='CASCADE'), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    generation = db.Column(db.String(36), nullable=False)
    entry_id = db.Column(db.String(36))
    interrupted = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime(timezone=True))


class CueMutation(db.Model):
    __tablename__ = 'cue_mutations'
    token = db.Column(db.String(36), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    fingerprint = db.Column(db.String(64), nullable=False)
