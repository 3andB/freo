"""Station domain rules; no systemd or shell access."""
import re
from flask import current_app
from sqlalchemy import text
from app.extensions import db
from app.models import Station, StreamMount

SLUG_PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')
RESERVED = {'admin', 'status', 'server_version', 'freo-test'}


def validate_slug(slug):
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug) or slug in RESERVED:
        raise ValueError('Invalid or reserved station slug')
    return slug


def create_station(name, slug, description='', *, pending=False, timezone_name='UTC'):
    from app.services.schedule import validate_timezone
    timezone_name = validate_timezone(timezone_name)
    validate_slug(slug)
    name = name.strip() if isinstance(name, str) else ''
    if not name or len(name) > 120:
        raise ValueError('Station name must be 1-120 characters')
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError('Description is too long')
    allocation_lock()
    from app.models import StationAlias
    if Station.query.filter(db.or_(Station.slug == slug, Station.public_slug == slug)).first() or db.session.get(StationAlias, slug):
        raise ValueError('Station slug already exists')
    limit = current_app.config['FREO_MAX_STATIONS']
    if limit and active_stations().count() >= limit:
        raise ValueError(f'This installation allows a maximum of {limit} stations')
    station = Station(timezone=timezone_name, lifecycle_state='pending_create' if pending else 'ready', name=name, slug=slug, description=description, enabled=True, desired_state='stopped')
    station.stream = StreamMount(format='mp3', bitrate=64, enabled=True)
    db.session.add(station)
    db.session.flush()
    from app.services.music_tags import seed_starter_tags
    seed_starter_tags(station.id)
    from app.services.playlists import seed_playlists
    seed_playlists(station.id)
    db.session.commit()
    return station


def get_station(slug):
    validate_slug(slug)
    return active_stations().filter_by(slug=slug).first()


def set_enabled(station, enabled):
    allocation_lock()
    db.session.refresh(station)
    if station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'):
        raise ValueError('Station is being deleted')
    station.enabled = bool(enabled)
    if not enabled:
        station.desired_state = 'stopped'
    db.session.commit()


def public_station(station):
    return {
        'name': station.name,
        'slug': station.slug,
        'description': station.description,
        'city': station.city,
        'region': station.region,
        'player_path': '/player/' + (station.public_slug or station.slug),
        'logo_path': '/station-assets/' + station.slug + '/logo.png?v=' + station.logo.version if station.logo else None,
        'contact_email': station.contact_email if station.publish_contact else None,
        'phone': station.phone if station.publish_contact else None,
        'enabled': station.enabled,
        'desired_state': station.desired_state,
        'lifecycle_state': station.lifecycle_state,
        'format': station.stream.format,
        'bitrate': station.stream.bitrate,
        'stream_path': station.stream.public_path,
    }


def update_station(station, *, name, description, public_slug, timezone_name, user, commit=True):
    from app.models import StationAlias
    from app.services.schedule import validate_timezone
    from app.services.programming import clean_text
    from app.services.admin_media import audit
    name = clean_text(name, 120, True)
    description = clean_text(description, 500)
    public_slug = validate_slug(public_slug)
    timezone_name = validate_timezone(timezone_name)
    allocation_lock()
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
    if commit:
        db.session.commit()
    return station


def public_station_for(slug):
    from app.models import StationAlias
    validate_slug(slug)
    station = Station.query.filter(db.or_(Station.slug == slug, Station.public_slug == slug)).first()
    alias = db.session.get(StationAlias, slug) if not station else None
    result = station or (alias.station if alias else None)
    return result if result and not result.deleted_at and result.lifecycle_state not in ('pending_delete', 'delete_failed') else None


def active_stations():
    return Station.query.filter(Station.deleted_at.is_(None))


def allocation_lock():
    # A table lock also serializes creation when there are ZERO station rows.
    # SQLite serializes writes; production PostgreSQL needs an explicit lock.
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(text('LOCK TABLE stations IN SHARE ROW EXCLUSIVE MODE'))
    elif db.session.get_bind().dialect.name == 'sqlite':
        connection = db.session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')


def request_delete(station, user_id=None):
    from app.services.admin_media import audit
    allocation_lock()
    db.session.refresh(station)
    if station.deleted_at:
        return station
    station.lifecycle_state = 'pending_delete'
    station.lifecycle_error = ''
    station.enabled = False
    station.desired_state = 'stopped'
    if station.automation:
        station.automation.enabled = False
    audit('station_delete_requested', user_id=user_id, station_id=station.id,
          target_type='station', target_id=station.slug,
          summary='Stop and remove station runtime; retain media and history')
    db.session.commit()
    return station


def deletion_impact(station):
    from app.models import Track, ScheduleProgram, TimedEvent, EventBlock
    from app.services.availability import shared
    songs = Track.query.filter_by(station_id=station.id, deleted_at=None).all()
    return dict(songs=len(songs), shared_songs=sum(shared(song) for song in songs),
                programs=ScheduleProgram.query.filter_by(station_id=station.id).count(),
                events=TimedEvent.query.filter_by(station_id=station.id).count(),
                blocks=EventBlock.query.filter_by(station_id=station.id).count())
