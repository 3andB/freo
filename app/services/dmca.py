"""Private report intake. No moderation or playback side effects."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import re
import uuid
from urllib.parse import urlsplit

from flask import current_app, request
from sqlalchemy import or_, text
from app.extensions import db
from app.models import DMCACase, Station, StationDomain, Track

STATUSES = ('OPEN', 'REVIEWING', 'ACTIONED', 'REJECTED', 'CLOSED')
FIELDS = (
    ('supplied_track_id', 'Freo Track ID (optional)', 64, False),
    ('station_text', 'Station name or URL', 500, True),
    ('copyrighted_work', 'Copyrighted work being claimed', 5000, True),
    ('material_location', 'Description/location of allegedly infringing material', 5000, True),
    ('claimant_name', 'Claimant name', 200, True),
    ('claimant_email', 'Claimant email', 254, True),
    ('signature', 'Electronic signature/name', 200, True),
)


class RateLimited(ValueError):
    pass


def validate(form):
    values = {}
    for key, label, limit, required in FIELDS:
        value = form.get(key, '').strip()
        if len(value) > limit or (required and not value):
            raise ValueError(f'{label}: enter {"1–" if required else "up to "}{limit} characters')
        if any(ord(char) < 32 and char not in '\r\n\t' for char in value):
            raise ValueError(f'{label}: invalid control character')
        values[key] = value
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', values['claimant_email']):
        raise ValueError('Enter a valid email address')
    if form.get('good_faith') != 'yes' or form.get('authorized') != 'yes':
        raise ValueError('Both statements must be confirmed')
    values.update(good_faith=True, authorized=True)
    return values


def reported_station(value):
    """Resolve only local records, never fetch a claimant-supplied URL."""
    row = Station.query.filter(or_(Station.name == value, Station.slug == value,
                                  Station.public_slug == value)).all()
    if len(row) == 1:
        return row[0]
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https'):
            return None
        domain = StationDomain.query.filter_by(hostname=url.hostname, enabled=True).filter(StationDomain.verified_at.isnot(None)).first()
        if domain:
            return domain.station
        from app.services.station_domains import installation_hosts
        if url.hostname in installation_hosts() and url.path.startswith('/player/'):
            slug = url.path.removeprefix('/player/').rstrip('/')
            return Station.query.filter(or_(Station.slug == slug, Station.public_slug == slug)).first()
    except ValueError:
        pass
    return None


def client_address():
    address = request.remote_addr or 'unknown'
    if address in current_app.config.get('DMCA_TRUSTED_PROXY_IPS', ()):
        try:
            address = str(ipaddress.ip_address(request.headers.get('X-Real-IP', '')))
        except ValueError:
            pass
    return address


def submit(form):
    values = validate(form)
    now = datetime.now(timezone.utc)
    network_key = hmac.new(current_app.secret_key.encode(),
                          ('dmca:' + client_address()).encode(), hashlib.sha256).hexdigest()
    # Same database-backed pattern as listener feedback, with a network lock
    # because a report need not identify an existing station. Shared across workers.
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': network_key})
    count = DMCACase.query.filter_by(network_key=network_key).filter(DMCACase.created_at > now - timedelta(hours=1)).count()
    if count >= current_app.config.get('DMCA_REPORTS_PER_HOUR', 5):
        raise RateLimited('Too many reports. Please try again in an hour.')
    track = Track.query.filter_by(freo_track_id=values['supplied_track_id'].upper()).with_for_update().first() if values['supplied_track_id'] else None
    station = reported_station(values['station_text'])
    snapshot = {}
    if track:
        snapshot = dict(freo_track_id=track.freo_track_id, title=track.title, artist=track.artist,
                        sha256=track.checksum_sha256, isrc=track.isrc,
                        station_name=track.station.name, station_slug=track.station.public_slug or track.station.slug)
    if station:
        snapshot['reported_station_name'] = station.name
        snapshot['reported_station_slug'] = station.public_slug or station.slug
    row = DMCACase(reference='DMCA-' + uuid.uuid4().hex, created_at=now, **values,
                   track_id=track.id if track else None, station_id=track.station_id if track else None,
                   reported_station_id=station.id if station else None, snapshot=snapshot, network_key=network_key)
    db.session.add(row)
    db.session.commit()
    return row
