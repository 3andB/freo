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
    db.session.flush()
    from app.services.music_tags import seed_starter_tags
    seed_starter_tags(station.id)
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


def update_station(station, *, name, description, public_slug, timezone_name, user):
    from app.models import StationAlias
    from app.services.schedule import validate_timezone
    from app.services.programming import clean_text
    from app.services.admin_media import audit
    name = clean_text(name, 120, True)
    description = clean_text(description, 500)
    public_slug = validate_slug(public_slug)
    timezone_name = validate_timezone(timezone_name)
    # Serialize public-name allocation; uniqueness also protects concurrent edits.
    db.session.query(Station.id).order_by(Station.id).with_for_update().all()
    collision = Station.query.filter(Station.id != station.id, db.or_(Station.slug == public_slug, Station.public_slug == public_slug)).first()
    alias = db.session.get(StationAlias, public_slug)
    if collision or alias and alias.station_id != station.id:
        raise ValueError('That station URL is already in use')
    for previous in (station.slug, station.public_slug, public_slug):
        if previous and not db.session.get(StationAlias, previous):
            db.session.add(StationAlias(slug=previous, station_id=station.id))
    station.name, station.description = name, description
    station.public_slug, station.timezone = public_slug, timezone_name
    audit('station_details_updated', user_id=user.id, station_id=station.id, target_type='station', target_id=station.slug,
          summary='Station details and public URL updated; previous URLs retained')
    db.session.commit()
    return station


def public_station_for(slug):
    from app.models import StationAlias
    validate_slug(slug)
    station = Station.query.filter(db.or_(Station.slug == slug, Station.public_slug == slug)).first()
    alias = db.session.get(StationAlias, slug) if not station else None
    return station or (alias.station if alias else None)
