"""Central API coordinator, called only by the independent reporter process."""
import hashlib
import json
import random
import time
from flask import current_app
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import CentralInstallation, Station, CentralHourlyMetric
from app.services.station_domains import preferred_url
from .client import APIError, Client, MAX_BYTES, identity_response, license_response, timestamp, uuid_string
from .identity import IdentityStore
from .licensing import checkpoint
from .metrics import machine_snapshot, sample, station_state, wire_metric, observe_station


def installation():
    row = db.session.get(CentralInstallation, 1)
    if row is None:
        row = CentralInstallation(id=1)
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            row = db.session.get(CentralInstallation, 1)
            if row is None:
                raise
    return row


def metadata(station):
    with current_app.test_request_context():
        url = preferred_url(station)
    removed = bool(station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'))
    return dict(station_id=station.freo_station_id, name=station.name, description=station.description,
                genre=station.genre or None, categories=station.directory_categories,
                city=station.city or None, region=station.region or None, country=station.country or None,
                latitude=None, longitude=None, public_url=url if url.startswith(('https://', 'http://')) else None,
                directory_opt_in=bool(station.directory_opt_in and not removed))


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def sync_batches(items):
    """Unicode text can reach the byte limit before the station count limit."""
    batch = []
    for item in items:
        candidate = batch + [item]
        size = len(json.dumps({'stations': [payload for _, payload in candidate]},
                              allow_nan=False, separators=(',', ':')).encode())
        if batch and (len(candidate) > 20 or size > MAX_BYTES):
            yield batch
            batch = [item]
        else:
            batch = candidate
    if batch:
        yield batch


def validate_heartbeat(response, station_count, metric_count):
    try:
        timestamp(response['server_time'])
        for key, expected in [('stations_accepted', station_count), ('metrics_accepted', metric_count)]:
            if type(response[key]) is not int or response[key] != expected:
                raise ValueError()
        if type(response['next_heartbeat_seconds']) is not int or response['next_heartbeat_seconds'] != 3600:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise APIError('invalid_heartbeat_response') from None


class Reporter:
    def __init__(self, client_factory=Client):
        self.client_factory = client_factory
        self.store = IdentityStore(current_app.config['FREO_API_STATE_DIR'])
        self.startup = True

    def save_state(self, row, **values):
        row.state = dict(row.state, **values)
        db.session.commit()

    def due(self, row, name, now):
        state = row.state.get(name, {})
        return not state.get('blocked') and now >= state.get('due', 0) and now >= row.state.get('retry_after', 0)

    def success(self, row, name, now, interval=3600):
        self.save_state(row, **{name: {'due': now + interval + random.uniform(0, 60)}})
        if row.last_error.startswith(name + ':'):
            row.last_error = ''
        db.session.commit()

    def failure(self, row, name, now, error):
        count = min(row.state.get(name, {}).get('failures', 0) + 1, 7)
        delay = max(error.retry_after, min(3600, 60 * 2 ** (count - 1))) + random.uniform(0, 30)
        blocked = error.status in (400, 401, 404, 405, 409, 413, 415)
        self.save_state(row, **{name: {'due': now + delay, 'failures': count, 'blocked': blocked}},
                        retry_after=now + error.retry_after if error.retry_after else row.state.get('retry_after', 0))
        row.last_error = name + ':' + error.code
        if error.status == 401:
            row.registration_state = 'credentials_rejected'
        db.session.commit()
        current_app.logger.warning('Central API %s failed (%s); broadcasts unaffected', name, error.code)

    def register(self, row):
        saved = self.store.read()
        if saved and 'installation_id' in saved:
            if row.installation_id and saved['installation_id'] != row.installation_id:
                raise APIError('credential_identity_mismatch')
            row.installation_id = saved['installation_id']
            if row.registration_state != 'credentials_rejected':
                row.registration_state = 'registered'
            db.session.commit()
            return saved
        if row.installation_id:
            raise APIError('credentials_missing_recovery_required')
        if row.registration_state not in ('pending', 'retry_registration'):
            return None
        if saved and row.registration_state != 'retry_registration':
            row.registration_state = 'registration_uncertain'
            row.last_error = 'registration_response_not_saved'
            db.session.commit()
            return None
        # Durable marker BEFORE the non-idempotent request. A crash cannot retry it.
        self.store.write({'registration_attempted': True})
        row.registration_state = 'registration_uncertain'
        db.session.commit()
        response = self.client_factory(current_app.config['FREO_API_URL']).request('POST', '/v1/register',
                    {'manager_email': row.manager_email, 'installation': machine_snapshot()})
        saved = identity_response(response)
        self.store.write(saved)  # Credential is durable before any other API request.
        row.installation_id = saved['installation_id']
        row.registration_state = 'registered'
        row.last_error = ''
        db.session.commit()
        return saved

    def activate(self, row):
        pending = row.state.get('activation')
        if not pending or not pending.get('code'):
            return
        saved = self.store.read()
        existing = saved if saved and saved.get('installation_id') else None
        # Consume before the external exchange. A restart must not create a
        # second installation after a response or disk-write failure.
        row.state = {k: v for k, v in row.state.items() if k != 'activation'}
        if not existing:
            row.registration_state = 'registration_uncertain'
        db.session.commit()
        if pending['expires'] <= time.time():
            if not existing and not saved:
                row.registration_state = 'unconfigured'
                db.session.commit()
            raise APIError('activation_code_expired')
        if row.installation_id and (not existing or existing['installation_id'] != row.installation_id):
            raise APIError('credentials_missing_recovery_required')
        if not existing and saved:
            raise APIError('activation_uncertain_recovery_required')
        if not existing:
            self.store.write({'registration_attempted': True})
        connection = self.client_factory(current_app.config['FREO_API_URL'],
                                         existing['access_token'] if existing else None)
        try:
            response = connection.request('POST', '/v1/activate',
                {'activation_code': pending['code'], 'installation': machine_snapshot()})
        except APIError as error:
            if not existing and error.status in (400, 401, 409, 413, 415, 429):
                self.store.path.unlink(missing_ok=True)
                row.registration_state = 'unconfigured'
                db.session.commit()
            raise
        try:
            uuid_string(response['station_profile_id'])
            timestamp(response['server_time'])
            if response['token_type'] != 'Bearer' or response['heartbeat_interval_seconds'] != 3600:
                raise ValueError()
            credentials = existing or identity_response(response)
            if response['installation_id'] != credentials['installation_id']:
                raise ValueError()
            if existing and 'access_token' in response:
                raise ValueError()
            entitlement = license_response(response['license'], credentials['installation_id'])
        except (KeyError, ValueError, TypeError):
            raise APIError('invalid_activation_response') from None
        self.store.write(credentials)
        row.installation_id = credentials['installation_id']
        row.registration_state = 'registered'
        received = time.time()
        row.license_cache = {'entitlement': entitlement, 'received_at': received,
                            'checked_at': received, 'server_floor': timestamp(entitlement['server_time'])}
        row.state = dict(row.state, owner_profile_id=response['station_profile_id'], license={'due': 0}, report={'due': 0})
        row.last_error = ''
        db.session.commit()

    def license(self, row, client, now):
        response = client.request('GET', '/v1/license')
        entitlement = license_response(response, row.installation_id)
        received = time.time()
        row.license_cache = {'entitlement': entitlement, 'received_at': received,
                            'checked_at': received, 'server_floor': timestamp(entitlement['server_time'])}
        self.success(row, 'license', now, entitlement['refresh_after_seconds'])

    def report(self, row, client, now, on_air):
        stations = Station.query.order_by(Station.id).all()
        calls = 0
        dirty = [(station, metadata(station)) for station in stations]
        dirty = [(station, payload) for station, payload in dirty
                 if station_state(station).synced_digest != digest(payload)]
        for batch in sync_batches(dirty):
            if calls >= 6:
                break
            db.session.commit()
            response = client.request('POST', '/v1/stations/sync', {'stations': [payload for _, payload in batch]})
            calls += 1
            try:
                if not isinstance(response['stations'], list) or len(response['stations']) != len(batch):
                    raise ValueError()
                for item in response['stations']:
                    timestamp(item['created_at'])
                    timestamp(item['updated_at'])
                returned = {item['station_id'] for item in response['stations']}
                if returned != {station.freo_station_id for station, _ in batch}:
                    raise ValueError()
                timestamp(response['server_time'])
            except (KeyError, TypeError, ValueError):
                raise APIError('invalid_sync_response') from None
            for station, payload in batch:
                station_state(station).synced_digest = digest(payload)
            db.session.commit()
        # Rotate batches fairly across installations larger than one request.
        cursor = row.state.get('station_cursor', 0)
        eligible = [station for station in stations if station.id in on_air and station_state(station).synced_digest]
        eligible = [s for s in eligible if s.id > cursor] + [s for s in eligible if s.id <= cursor]
        heartbeat_sent = False
        for offset in range(0, len(eligible), 20):
            if calls >= 8:
                break
            batch, entries, sent = eligible[offset:offset + 20], [], []
            for station in batch:
                online, _ = observe_station(station)
                if online is None:
                    continue
                metrics = CentralHourlyMetric.query.filter_by(station_id=station.id, sent=False).filter(
                    CentralHourlyMetric.period_start < int(now // 3600) * 3600,
                    CentralHourlyMetric.period_start >= max(now, time.time()) - 7 * 86400 + 60,
                    CentralHourlyMetric.observed_seconds > 0).order_by(CentralHourlyMetric.period_start).limit(5).all()
                entries.append(dict(station_id=station.freo_station_id, on_air=bool(online),
                                    metrics=[wire_metric(metric) for metric in metrics]))
                sent.extend(metrics)
            if not entries:
                continue
            db.session.commit()
            response = client.request('POST', '/v1/heartbeat', {'installation': machine_snapshot(), 'stations': entries})
            calls += 1
            validate_heartbeat(response, len(entries), len(sent))
            heartbeat_sent = True
            for metric in sent:
                metric.sent = True
            self.save_state(row, station_cursor=batch[-1].id)
        # Unknown station observations still allow installation-only reporting.
        if not heartbeat_sent:
            response = client.request('POST', '/v1/heartbeat', {'installation': machine_snapshot(), 'stations': []})
            validate_heartbeat(response, 0, 0)
        self.success(row, 'report', now)

    def tick(self, now=None):
        now = time.time() if now is None else now
        row = installation()
        checkpoint(row, now)
        db.session.commit()
        if row.registration_state == 'unconfigured':
            return
        try:
            self.activate(row)
            credentials = self.register(row)
        except APIError as error:
            row.last_error = error.code
            db.session.commit()
            current_app.logger.warning('Central API registration/storage needs attention (%s)', error.code)
            return
        if not credentials:
            return
        on_air = sample(now)
        if row.registration_state == 'credentials_rejected':
            return
        client = self.client_factory(current_app.config['FREO_API_URL'], credentials['access_token'])
        # A process start refreshes the license, while honoring persisted backoff.
        if self.startup and not row.state.get('license', {}).get('failures'):
            self.save_state(row, license={'due': 0})
        self.startup = False
        # Bound total API calls across retries and frequent process restarts.
        if not any(self.due(row, name, now) for name in ('license', 'report')):
            return
        window = int(now // 3600)
        budget = row.state.get('budget', {})
        if budget.get('hour') != window:
            budget = {'hour': window, 'reserved': 0}
        if budget['reserved'] >= 90:
            return
        self.save_state(row, budget={'hour': window, 'reserved': budget['reserved'] + 9})
        for name, operation in [('license', lambda: self.license(row, client, now)),
                                ('report', lambda: self.report(row, client, now, on_air))]:
            if not self.due(row, name, now):
                continue
            try:
                operation()
            except APIError as error:
                if error.code == 'station_not_synced':
                    for station in Station.query:
                        station_state(station).synced_digest = None
                    db.session.commit()
                    error = APIError('station_not_synced')  # Sync before the next conservative retry.
                self.failure(row, name, now, error)
                if error.status == 401 or error.retry_after:
                    break
