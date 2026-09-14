"""Station domain rules; no systemd or shell access."""
import re
from app.extensions import db
from app.models import Station, StreamMount

SLUG_PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')
RESERVED = {'admin', 'status', 'server_version', 'freo-test'}


def validate_slug(slug):
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug) or slug in RESERVED:
        raise ValueError('Invalid or reserved station slug')
    return slug


def create_station(name, slug, description=''):
    validate_slug(slug)
    name = name.strip() if isinstance(name, str) else ''
    if not name or len(name) > 120:
        raise ValueError('Station name must be 1-120 characters')
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError('Description is too long')
    if db.session.query(Station.id).filter_by(slug=slug).first():
        raise ValueError('Station slug already exists')
    station = Station(name=name, slug=slug, description=description, enabled=True, desired_state='stopped')
    station.stream = StreamMount(format='mp3', bitrate=64, enabled=True)
    db.session.add(station)
    db.session.commit()
    return station


def get_station(slug):
    validate_slug(slug)
    return db.session.query(Station).filter_by(slug=slug).first()


def set_enabled(station, enabled):
    station.enabled = bool(enabled)
    if not enabled:
        station.desired_state = 'stopped'
    db.session.commit()


def public_station(station):
    return {
        'name': station.name,
        'slug': station.slug,
        'description': station.description,
        'enabled': station.enabled,
        'desired_state': station.desired_state,
        'format': station.stream.format,
        'bitrate': station.stream.bitrate,
        'stream_path': station.stream.public_path,
    }
