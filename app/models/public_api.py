"""Revocable public API authority, independent of browser sessions."""
from datetime import datetime, timezone

from app.extensions import db


class ApiCredential(db.Model):
    __tablename__ = 'api_credentials'
    __table_args__ = (db.CheckConstraint("scope = 'read'", name='ck_api_credential_scope'),)
    id = db.Column(db.String(32), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    token_digest = db.Column(db.String(64), nullable=False)
    scope = db.Column(db.String(16), nullable=False, default='read')
    created_by = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    revoked_at = db.Column(db.DateTime(timezone=True))
    creator = db.relationship('AdminUser')
    grants = db.relationship('ApiCredentialStation', cascade='all, delete-orphan')


class ApiCredentialStation(db.Model):
    __tablename__ = 'api_credential_stations'
    credential_id = db.Column(db.String(32), db.ForeignKey('api_credentials.id', ondelete='CASCADE'), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    station = db.relationship('Station')


class ApiRateBucket(db.Model):
    __tablename__ = 'api_rate_buckets'
    kind = db.Column(db.String(16), primary_key=True)
    key = db.Column(db.String(64), primary_key=True)
    minute = db.Column(db.BigInteger, primary_key=True, index=True)
    count = db.Column(db.Integer, nullable=False)
