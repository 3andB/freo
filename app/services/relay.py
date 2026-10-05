"""Relay administration and worker reconciliation; Liquidsoap owns playback."""
from datetime import datetime, timedelta, timezone
import json
from flask import current_app
from sqlalchemy import update
from app.extensions import db
from app.models import StationRelay, AuditEvent
from app.services.relay_transport import validate_url, allowed_addresses, RelayTransport


def save(station, values, user):
    from app.services.admin_auth import can_manage_programming
    if not can_manage_programming(user, station):
        raise ValueError('Station administration permission required.')
    try:
        revision = int(values.get('relay_revision', ''))
    except (TypeError, ValueError):
        raise ValueError('Refresh relay settings before saving.') from None
    enabled = values.get('relay_enabled') == 'yes'
    url = values.get('relay_url', '').strip()
    if enabled or url:
        parsed = validate_url(url)
        try:
            if enabled:
                allowed_addresses(parsed, current_app.config['FREO_RELAY_PRIVATE_NETWORKS'])
        except OSError:
            raise ValueError('Upstream hostname could not be resolved.') from None
    row = db.session.get(StationRelay, station.id)
    if row is None:
        if revision != 0:
            raise ValueError('Relay settings changed. Refresh before saving.')
        # Serialize first creation on the parent, including PostgreSQL callers.
        from app.models import Station
        db.session.query(Station).filter_by(id=station.id).with_for_update().one()
        row = db.session.get(StationRelay, station.id, populate_existing=True)
        if row is not None:
            raise ValueError('Relay settings changed. Refresh before saving.')
        row = StationRelay(station_id=station.id, enabled=enabled, url=url)
        db.session.add(row)
    else:
        changed = db.session.execute(update(StationRelay).where(StationRelay.station_id == station.id,
            StationRelay.revision == revision).values(enabled=enabled, url=url, revision=revision+1, error=None,
                                                     observation=None, observed_at=None))
        if changed.rowcount != 1:
            raise ValueError('Relay settings changed. Refresh before saving.')
    if enabled:
        from app.services.automation import state_for
        state = state_for(station)
        state.enabled = True
        if state.operator_mode == 'AUTO':
            state.hold = False
    db.session.add(AuditEvent(station_id=station.id, admin_user_id=user.id, action='relay_settings', target_type='station', target_id=str(station.id),
                             summary='Upstream relay enabled' if enabled else 'Upstream relay disabled'))


def describe(station):
    row = db.session.get(StationRelay, station.id)
    now = datetime.now(timezone.utc)
    fresh = bool(row and row.observed_at and 0 <= (now-row.observed_at.replace(tzinfo=timezone.utc)).total_seconds() < 10
                 and row.applied_revision == row.revision and station.desired_state == 'running')
    data = dict(row.observation or {}) if fresh else {}
    return dict(enabled=bool(row and row.enabled), revision=row.revision if row else 0,
        pending=bool(row and row.applied_revision != row.revision), connected=data.get('connected'),
        ready=data.get('ready'), selected=data.get('selected', False), source=data.get('source', 'unknown'),
        title=data.get('title', ''), artist=data.get('artist', ''), fresh=fresh,
        observed_at=row.observed_at.isoformat() if row and row.observed_at else None,
        last_failure_at=row.last_failure_at.isoformat() if row and row.last_failure_at else None,
        last_reconnect_at=row.last_reconnect_at.isoformat() if row and row.last_reconnect_at else None,
        error=row.error if row else None)


def read_engine(slug):
    from app.services.playout_queue import _command
    data = json.loads(_command(slug, 'freo_relay.state'))
    if not isinstance(data, dict) or any(type(data.get(key)) is not bool for key in ('connected','ready','selected')):
        raise ValueError('Invalid relay observation')
    if data.get('source') not in ('relay','automation','dj','microphone','cart','event','tone'):
        raise ValueError('Invalid relay source')
    result = {key:data[key] for key in ('connected','ready','selected','source')}
    for key in ('title','artist'):
        result[key] = ''.join(c for c in str(data.get(key, '')) if c.isprintable())[:200]
    for key in ('failure','reconnect'):
        value = float(data.get(key, 0))
        if not 0 <= value <= datetime.now(timezone.utc).timestamp()+60:
            raise ValueError('Invalid relay timestamp')
        result[key] = value
    return result


def reconcile(station, reader):
    from app.services.playout_queue import _command, socket_identity
    row = db.session.get(StationRelay, station.id)
    if row is None:
        return None  # No new socket calls for stations that never configured relay.
    try:
        identity = (row.revision, socket_identity(station.slug))
        applied = getattr(reader, 'relay_applied', {})
        if applied.get(station.id) != identity:
            transport = getattr(reader, 'relay_transport', None)
            if row.enabled and transport is None:
                transport = reader.relay_transport = RelayTransport(
                    int(current_app.config['FREO_RELAY_TRANSPORT_PORT']), current_app.config['FREO_RELAY_PRIVATE_NETWORKS'])
            url = transport.configure(station.id, row.url if row.enabled else '') if transport else ''
            # Only the local capability crosses the engine socket, never the upstream URL.
            payload = str(row.revision) + ' ' + (url or '-')
            _command(station.slug, 'freo_relay.apply ' + payload)
            applied[station.id] = identity
            reader.relay_applied = applied
            row.applied_revision = row.revision
        from app.models import TimedEventOccurrence, EventBlockExecution
        held = bool(TimedEventOccurrence.query.filter_by(station_id=station.id).filter(
            TimedEventOccurrence.state.in_(('QUEUED', 'STARTED'))).first() or
            EventBlockExecution.query.filter_by(station_id=station.id).filter(
                EventBlockExecution.state.in_(('QUEUED', 'STARTED')),
                EventBlockExecution.timed_event_occurrence_id.isnot(None)).first())
        _command(station.slug, 'freo_relay.hold ' + ('true' if held else 'false'))
        data = read_engine(station.slug)
        row.observation = data
        row.observed_at = datetime.now(timezone.utc)
        row.error = None
        for source, field in [('failure', 'last_failure_at'), ('reconnect', 'last_reconnect_at')]:
            if data[source]:
                setattr(row, field, datetime.fromtimestamp(data[source], timezone.utc))
        db.session.commit()
        return data
    except (OSError, RuntimeError, ValueError):
        row.error = 'Relay engine unavailable; configuration will retry. Station render may need updating.'
        row.observation = None
        db.session.commit()
        return None


def defer_events(station):
    from app.services.timed_events import generate_occurrences, expire_due
    from app.models import TimedEventOccurrence
    now = datetime.now(timezone.utc)
    generate_occurrences(station, now)
    expire_due(station, now)
    for event in TimedEventOccurrence.query.filter_by(station_id=station.id).filter(
            TimedEventOccurrence.state.in_(('PENDING','READY')), TimedEventOccurrence.scheduled_for_utc <= now).all():
        event.failure_reason = 'waiting_for_relay'
    db.session.commit()


def reserve_events(station):
    """Atomically fence recovery against an event being prepared by this tick."""
    if not station.relay or not station.relay.enabled:
        return True
    from app.models import TimedEventOccurrence
    from app.services.timed_events import generate_occurrences, expire_due
    now = datetime.now(timezone.utc)
    generate_occurrences(station, now)
    expire_due(station, now)
    due = TimedEventOccurrence.query.filter_by(station_id=station.id).filter(
        TimedEventOccurrence.state.in_(('PENDING','READY')),
        TimedEventOccurrence.scheduled_for_utc <= now+timedelta(seconds=20)).first()
    if due is None:
        return True
    from app.services.playout_queue import _command
    return _command(station.slug, 'freo_relay.reserve') == 'OK'


def suspend(station_id, reader):
    """Revoke transport when the existing station lifecycle stops a station."""
    transport = getattr(reader, 'relay_transport', None)
    if transport is not None:
        transport.configure(station_id, '')
    getattr(reader, 'relay_applied', {}).pop(station_id, None)
