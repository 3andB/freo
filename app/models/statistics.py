"""Local analytics; scope 0 denotes all channels, positive scopes are Station IDs."""
from app.extensions import db


class StatsState(db.Model):
    __tablename__ = 'stats_states'
    scope = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.JSON, nullable=False, default=dict)


class AudienceSample(db.Model):
    __tablename__ = 'stats_samples'
    scope = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.BigInteger, primary_key=True, index=True)
    listeners = db.Column(db.Integer)
    online = db.Column(db.Boolean)


class StatsBucket(db.Model):
    __tablename__ = 'stats_buckets'
    scope = db.Column(db.Integer, primary_key=True)
    resolution = db.Column(db.String(12), primary_key=True)
    at = db.Column(db.BigInteger, primary_key=True, index=True)
    observed_seconds = db.Column(db.Float, nullable=False, default=0)
    listener_seconds = db.Column(db.Float, nullable=False, default=0)
    online_seconds = db.Column(db.Float, nullable=False, default=0)
    peak = db.Column(db.Integer, nullable=False, default=0)
    bytes_sent = db.Column(db.BigInteger, nullable=False, default=0)
    transfer_seconds = db.Column(db.Float, nullable=False, default=0)


class AudiencePresence(db.Model):
    __tablename__ = 'stats_presence'
    scope = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(12), primary_key=True)
    key = db.Column(db.String(64), primary_key=True)
    first_seen = db.Column(db.BigInteger, nullable=False)
    last_seen = db.Column(db.BigInteger, nullable=False, index=True)
    geo = db.Column(db.JSON, nullable=False, default=dict)


class GeoBucket(db.Model):
    __tablename__ = 'stats_geo_buckets'
    scope = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(12), primary_key=True)
    place = db.Column(db.String(64), primary_key=True)
    at = db.Column(db.BigInteger, primary_key=True, index=True)
    geo = db.Column(db.JSON, nullable=False, default=dict)
    sessions = db.Column(db.Integer, nullable=False, default=0)
    observed_seconds = db.Column(db.Float, nullable=False, default=0)


class GeoReach(db.Model):
    __tablename__ = 'stats_geo_reach'
    scope = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(12), primary_key=True)
    place = db.Column(db.String(64), primary_key=True)
    geo = db.Column(db.JSON, nullable=False, default=dict)
    first_seen = db.Column(db.BigInteger, nullable=False)
    last_seen = db.Column(db.BigInteger, nullable=False)
    sessions = db.Column(db.BigInteger, nullable=False, default=0)
    observed_seconds = db.Column(db.Float, nullable=False, default=0)


class StorageSnapshot(db.Model):
    __tablename__ = 'stats_storage'
    scope = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.BigInteger, primary_key=True, index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)


class BroadcastIncident(db.Model):
    __tablename__ = 'stats_incidents'
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(32), nullable=False)
    started_at = db.Column(db.BigInteger, nullable=False, index=True)
    ended_at = db.Column(db.BigInteger)
    detail = db.Column(db.String(200), nullable=False, default='')


class FeedbackTransition(db.Model):
    __tablename__ = 'stats_feedback'
    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.Integer, nullable=False, index=True)
    track_id = db.Column(db.Integer, nullable=False, index=True)
    vote_id = db.Column(db.Integer, nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    at = db.Column(db.BigInteger, nullable=False, index=True)
    old_value = db.Column(db.Integer, nullable=False)
    new_value = db.Column(db.Integer, nullable=False)
    old_excluded = db.Column(db.Boolean, nullable=False)
    new_excluded = db.Column(db.Boolean, nullable=False)
    __table_args__ = (db.UniqueConstraint('vote_id', 'revision', name='uq_stats_feedback_revision'),)
