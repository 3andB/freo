"""Optional latest-state sharing, exclusively in the serialized reporter worker."""
from datetime import datetime, timezone
import hashlib
import json
import random
import time
from flask import current_app
import unicodedata

from app.extensions import db
from app.models import LiveQueueSnapshot, SelectionDecision, Station
from .client import APIError, MAX_BYTES, timestamp
from .metrics import channel_lifecycle, seconds, station_state


def text(value):
    if not isinstance(value, str):
        return None
    value = ''.join(c for c in value if unicodedata.category(c) not in ('Cc', 'Cs')).strip()[:500]
    return value or None


def fresh(at, now, limit=15):
    return at is not None and 0 <= now - seconds(at) < limit


def playback(station, now):
    """Read confirmed worker output; no engine commands, selection or audio changes."""
    from app.services.broadcast_status import observation
    online, _ = observation(station.slug)
    if online is None:
        return None
    result = dict(station_id=station.freo_station_id, on_air=online, title=None, artist=None,
                  observed_at=datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z'))
    if not online:
        return result
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    if not snapshot or snapshot.error_code or not fresh(snapshot.observed_at, now):
        return result
    show = snapshot.show_observation or {}
    try:
        show_at = datetime.fromisoformat(show['observed_at'])
    except (KeyError, ValueError, TypeError):
        show_at = None
    if fresh(show_at, now) and show.get('source') == 'MIC':
        return result
    relay = station.relay
    if relay and relay.applied_revision == relay.revision and fresh(relay.observed_at, now, 10):
        source = (relay.observation or {}).get('source')
        if source in ('microphone', 'tone'):
            return result
        if source == 'relay':
            result.update(title=text(relay.observation.get('title')), artist=text(relay.observation.get('artist')))
            return result
    mixer = snapshot.mixer or {}
    if mixer.get('tone'):
        return result
    # Start with final-output identity; DJ crossfades can contain two audible songs.
    gains = {snapshot.current_decision_id: 1.0} if snapshot.current_decision_id else {}
    if mixer.get('mode') == 'DJ_BOOTH':
        gains = {}
        for deck in ('a', 'b'):
            gain = (mixer.get('transition') or {}).get(deck + '_gain')
            if gain is None:
                gain = 1 - mixer.get('crossfader', 0) if deck == 'a' else mixer.get('crossfader', 0)
            if mixer.get(deck + '_playing') and mixer.get(deck + '_id') and gain > 0:
                gains[mixer[deck + '_id']] = gain
        if mixer.get('auto_standby') and mixer.get('auto_id') and mixer.get('auto_gain', 0) > 0:
            gains[mixer['auto_id']] = mixer['auto_gain']
        final = db.session.get(SelectionDecision, snapshot.current_decision_id) if snapshot.current_decision_id else None
        if final and final.station_id == station.id and (final.selection_method in ('timed_event', 'event_block')
                                                       or final.cart_mode == 'TAKEOVER'):
            gains = {final.id: 1.0}
    rows = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.id.in_(list(gains)), SelectionDecision.status == 'started',
        SelectionDecision.started_at.isnot(None)).all() if gains else []
    row = max(rows, key=lambda r: (gains[r.id], seconds(r.started_at), r.id), default=None)
    if row:
        values = dict(title=row.track.title, artist=row.track.artist) if row.track else row.performance_snapshot or {}
        result.update(title=text(values.get('title')), artist=text(values.get('artist')))
    return result


def signature(entry):
    return hashlib.sha256(json.dumps({k: v for k, v in entry.items() if k != 'observed_at'},
                                    sort_keys=True).encode()).hexdigest()


def batches(entries):
    batch = []
    for entry in entries:
        candidate = batch + [entry]
        if batch and (len(candidate) > 100 or len(json.dumps({'stations': candidate},
                separators=(',', ':'), allow_nan=False).encode()) > MAX_BYTES):
            yield batch
            batch = []
        batch.append(entry)
    if batch:
        yield batch


def retry(reporter, row, key, now, error):
    old = row.state.get(key, {})
    failures = min(old.get('failures', 0) + 1, 8)
    delay = max(error.retry_after, min(60, 5 * 2 ** (failures - 1)) + random.uniform(0, 1))
    # Retry-After starts at receipt, not the earlier sampling/request time.
    failed_at = max(now, time.time())
    reporter.save_state(row, **{key: dict(old, failures=failures, due=failed_at + delay, error=error.code)})
    if error.status == 401:
        row.registration_state = 'credentials_rejected'
        row.last_error = key + ':unauthorized'
        db.session.commit()


def fast_tick(reporter, now):
    from . import installation, metadata, digest
    row = installation()
    if not row.installation_id or row.registration_state == 'credentials_rejected':
        return
    probe_at = row.state.get('now_playing_probe_at', 0)
    if probe_at and now >= probe_at:
        # Recheck optional support only when its own retry is due. A rejected
        # song report must not block due heartbeats behind a shared probe timer.
        reporter.contract_checked = False
        reporter.save_state(row, now_playing_probe_at=0)
    if not reporter.detect_contract(row, now):
        return
    try:
        credentials = reporter.store.read()
        if not credentials or credentials.get('installation_id') != row.installation_id:
            raise APIError('credentials_missing_recovery_required')
    except APIError as error:
        retry(reporter, row, 'now_playing', now, error)
        return
    client = reporter.client_factory(current_app.config['FREO_API_URL'], credentials['access_token'])
    # This also handles withdrawals when now-playing isn't supported remotely.
    sync = row.state.get('directory_sync', {})
    if now >= sync.get('due', 0) and now >= row.state.get('retry_after', 0):
        try:
            reporter.sync_metadata(row, client, now, reserve=True)
            reporter.save_state(row, directory_sync={})
        except APIError as error:
            retry(reporter, row, 'directory_sync', now, error)
            if error.retry_after:
                reporter.save_state(row, retry_after=time.time() + error.retry_after)
            if error.status == 401:
                return
    state = row.state.get('now_playing', {})
    if (not reporter.now_playing_supported or now < state.get('due', 0)
            or now < row.state.get('retry_after', 0)):
        return
    accepted = dict(state.get('accepted', {}))
    stations = Station.query.order_by(Station.id).populate_existing().all()
    entries = []
    for station in stations:
        if not station.directory_opt_in or channel_lifecycle(station) in ('deleted', 'retired'):
            continue
        payload = metadata(station, reporter.extended)
        if not payload['public_url'] or station_state(station).synced_digest != digest(payload):
            continue
        entry = playback(station, now)
        if entry is None:
            continue
        prior = accepted.get(entry['station_id'], {})
        if (reporter.now_playing_startup or signature(entry) != prior.get('digest')
                or now - prior.get('at', 0) >= 50):
            entries.append(entry)
    reporter.now_playing_startup = False
    for batch in batches(entries):
        # Endpoint-specific budget leaves headroom under the shared IP limit.
        calls = [at for at in row.state.get('now_playing_calls', []) if now - at < 60]
        if len(calls) >= 60:
            return
        reporter.save_state(row, now_playing_calls=calls + [now])
        # Previous batches may have waited on the network: resample immediately.
        outgoing = []
        for old in batch:
            station = Station.query.filter_by(freo_station_id=old['station_id']).populate_existing().one()
            if station.directory_opt_in and channel_lifecycle(station) not in ('deleted', 'retired'):
                # Real sampling time, including retries after a slow request.
                sampled = playback(station, time.time())
                if sampled is not None and station_state(station).synced_digest == digest(metadata(station, reporter.extended)):
                    outgoing.append(sampled)
        if not outgoing:
            continue
        try:
            response = client.request('POST', '/v1/now-playing', {'stations': outgoing})
            try:
                timestamp(response['server_time'])
                if (type(response['stations_accepted']) is not int or response['stations_accepted'] != len(outgoing)
                    or type(response['stations_updated']) is not int or not 0 <= response['stations_updated'] <= len(outgoing)
                    or type(response['next_report_seconds']) is not int or response['next_report_seconds'] <= 0):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise APIError('invalid_now_playing_response') from None
        except APIError as error:
            if error.code in ('station_not_synced', 'directory_not_enabled'):
                for entry in outgoing:
                    station = Station.query.filter_by(freo_station_id=entry['station_id']).one()
                    station_state(station).synced_digest = None
                db.session.commit()
            if error.status in (400, 404, 405, 409, 413):
                reporter.now_playing_supported = False
                capability = dict(row.state.get('now_playing_capability', {}),
                                  supported=False, paused_reason=error.code)
                reporter.save_state(row, now_playing_probe_at=now + 60,
                                    now_playing_capability=capability)
            retry(reporter, row, 'now_playing', now, error)
            return
        for entry in outgoing:
            accepted[entry['station_id']] = dict(digest=signature(entry), at=timestamp(entry['observed_at']))
        # Keep only latest acknowledgement digests, never a song history.
        valid = {s.freo_station_id for s in stations if s.directory_opt_in}
        accepted = {key: value for key, value in accepted.items() if key in valid}
        reporter.save_state(row, now_playing=dict(accepted=accepted, server_time=response['server_time'],
                            stations_accepted=len(outgoing), due=0))
