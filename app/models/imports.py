"""Durable review drafts; preparation never creates a library track."""
from datetime import datetime, timezone
from uuid import uuid4
from app.extensions import db


def now():
    return datetime.now(timezone.utc)


class MusicImportSession(db.Model):
    __tablename__ = 'music_import_sessions'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    groups = db.Column(db.JSON, nullable=False, default=dict)
    station = db.relationship('Station')
    items = db.relationship('MusicImportItem', back_populates='session', cascade='all, delete-orphan', order_by='MusicImportItem.created_at')


class MusicImportItem(db.Model):
    __tablename__ = 'music_import_items'
    __table_args__ = (db.CheckConstraint("status IN ('pending','preparing','ready','failed','finalized','cancelled','expired')", name='ck_music_import_item_status'),)
    id = db.Column(db.String(36), primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey('music_import_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    relative_path = db.Column(db.String(1000), nullable=False, default='')
    size_bytes = db.Column(db.BigInteger, nullable=False)
    checksum = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    detected = db.Column(db.JSON, nullable=False, default=dict)
    choices = db.Column(db.JSON, nullable=False, default=dict)
    revision = db.Column(db.Integer, nullable=False, default=1)
    error = db.Column(db.String(240), nullable=False, default='')
    preview_id = db.Column(db.String(36))
    artwork = db.deferred(db.Column(db.LargeBinary))
    job_id = db.Column(db.String(36), db.ForeignKey('media_ingest_jobs.id', ondelete='SET NULL'))
    dismissed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    session = db.relationship('MusicImportSession', back_populates='items')
    job = db.relationship('MediaIngestJob')
