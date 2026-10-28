"""Station-owned upstream configuration; runtime observations contain no URLs."""
from app.extensions import db


class StationRelay(db.Model):
    __tablename__ = 'station_relays'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    url = db.Column(db.String(2048), nullable=False, default='', server_default='')
    revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    applied_revision = db.Column(db.Integer)
    observation = db.Column(db.JSON)
    observed_at = db.Column(db.DateTime(timezone=True))
    last_failure_at = db.Column(db.DateTime(timezone=True))
    last_reconnect_at = db.Column(db.DateTime(timezone=True))
    error = db.Column(db.String(160))
    station = db.relationship('Station', backref=db.backref('relay', uselist=False, cascade='all, delete-orphan'))
