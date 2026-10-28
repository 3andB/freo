"""Optional production records; playable audio always belongs to the normal catalog."""
from datetime import datetime, timezone
from uuid import uuid4
from app.extensions import db


def now():
    return datetime.now(timezone.utc)


class ProviderCredential(db.Model):
    __tablename__ = 'provider_credentials'
    provider = db.Column(db.String(24), primary_key=True)
    ciphertext = db.Column(db.Text)
    model = db.Column(db.String(120), nullable=False, default='')
    revision = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class StationProduction(db.Model):
    __tablename__ = 'station_production'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    script_provider = db.Column(db.String(24), nullable=False, default='')
    voice_id = db.Column(db.String(120), nullable=False, default='')
    model_id = db.Column(db.String(120), nullable=False, default='eleven_multilingual_v2')
    revision = db.Column(db.Integer, nullable=False, default=1)


class ProductionGrant(db.Model):
    __tablename__ = 'production_grants'
    __table_args__ = (db.ForeignKeyConstraint(['user_id', 'station_id'],
        ['dj_station_assignments.admin_user_id', 'dj_station_assignments.station_id'], ondelete='CASCADE'),)
    user_id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, primary_key=True)
    voice_tracking = db.Column(db.Boolean, nullable=False, default=False)
    ai_generation = db.Column(db.Boolean, nullable=False, default=False)
    playlists = db.Column(db.JSON, nullable=False, default=list)


class ProductionDraft(db.Model):
    __tablename__ = 'production_drafts'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    mode = db.Column(db.String(12), nullable=False)  # voice or ai
    title = db.Column(db.String(200), nullable=False)
    subtype = db.Column(db.String(24), nullable=False)
    spec = db.Column(db.JSON, nullable=False, default=dict)
    components = db.Column(db.JSON, nullable=False, default=dict)
    revision = db.Column(db.Integer, nullable=False, default=1)
    state = db.Column(db.String(24), nullable=False, default='draft')
    error = db.Column(db.String(240))
    ingest_job_id = db.Column(db.String(36), db.ForeignKey('media_ingest_jobs.id', ondelete='SET NULL'))
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, index=True)
    track = db.relationship('Track')
    station = db.relationship('Station')


class ProductionAttempt(db.Model):
    __tablename__ = 'production_attempts'
    __table_args__ = (db.UniqueConstraint('draft_id', 'request_id', name='uq_production_request'),)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id = db.Column(db.String(36), db.ForeignKey('production_drafts.id', ondelete='CASCADE'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    request_id = db.Column(db.String(36), nullable=False)
    action = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False, default='pending', index=True)
    inputs = db.Column(db.JSON, nullable=False, default=dict)
    provider = db.Column(db.String(24))
    credential_revision = db.Column(db.Integer)
    usage = db.Column(db.JSON, nullable=False, default=dict)
    error = db.Column(db.String(240))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))
    draft = db.relationship('ProductionDraft')
