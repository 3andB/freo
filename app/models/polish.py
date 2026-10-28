"""Optional public profiles owned by an individual station assignment."""
from app.extensions import db


class DJStationProfile(db.Model):
    __tablename__ = 'dj_station_profiles'
    user_id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, primary_key=True)
    bio = db.Column(db.String(1000), nullable=False, default='', server_default='')
    links = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    image = db.deferred(db.Column(db.LargeBinary))
    image_version = db.Column(db.String(64))
    revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    __table_args__ = (db.ForeignKeyConstraint(
        ['user_id', 'station_id'],
        ['dj_station_assignments.admin_user_id', 'dj_station_assignments.station_id'],
        ondelete='CASCADE'),)
