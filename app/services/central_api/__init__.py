"""Central API coordinator, called only by the independent reporter process."""
import hashlib
import json
import random
import secrets
import time
from flask import current_app
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.version import VERSION
from app.models import CentralInstallation, CentralConnectionCheck, Station, CentralHourlyMetric
from app.services.station_domains import preferred_url
from .client import APIError, Client, MAX_BYTES, identity_response, license_response, timestamp, uuid_string
from .identity import IdentityStore
from .licensing import checkpoint
from .metrics import machine_snapshot, sample, station_state, wire_metric, observe_station
from .releases import heartbeat_release, check_version


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
                row.registration_state = 'enrolled'
            db.session.commit()
            return saved
        if row.installation_id:
            raise APIError('credentials_missing_recovery_required')
        if (saved and 'enrollment_token' in saved) or row.registration_state in ('unconfigured', 'activation_queued', 'enrolling'):
            return self.enroll(row, saved)
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
        row.registration_state = 'enrolled'
        row.last_error = ''
        db.session.commit()
        return saved

    def enroll(self, row, saved):
        now = time.time()
        if not self.due(row, 'enrollment', now):
            return None
        if saved and 'enrollment_token' not in saved:
            raise APIError('registration_uncertain_recovery_required')
        if not saved:
            if row.registration_state == 'enrolling':
                raise APIError('credentials_missing_recovery_required')
            saved = {'enrollment_token': 'freo_' + secrets.token_urlsafe(32)}
            self.store.write(saved)  # Durable before sending, including on process crashes.
        row.registration_state = 'enrolling'
        db.session.commit()
        token = saved['enrollment_token']
        try:
            response = self.client_factory(current_app.config['FREO_API_URL'], token).request(
                'POST', '/v1/enroll', {'installation': machine_snapshot()})
            credentials = identity_response(dict(response, access_token=token))
        except APIError as error:
            self.failure(row, 'enrollment', now, error)
            return None
        self.store.write(credentials)
        row.installation_id = credentials['installation_id']
        row.registration_state = 'enrolled'
        self.success(row, 'enrollment', now)
        return credentials

    def activate(self, row, credentials):
        pending = row.state.get('activation')
        now = time.time()
        if not pending or not pending.get('code') or not self.due(row, 'claim', now):
            return
        try:
            if pending['expires'] <= now:
                raise APIError('activation_code_expired', status=400)
            connection = self.client_factory(current_app.config['FREO_API_URL'], credentials['access_token'])
            response = connection.request('POST', '/v1/activate',
                {'activation_code': pending['code'], 'installation': machine_snapshot()})
            try:
                profile_id = uuid_string(response['station_profile_id'])
                timestamp(response['server_time'])
                if (response['token_type'] != 'Bearer' or response['heartbeat_interval_seconds'] != 3600
                        or response['installation_id'] != credentials['installation_id'] or 'access_token' in response):
                    raise ValueError()
                entitlement = license_response(response['license'], credentials['installation_id'])
            except (KeyError, ValueError, TypeError):
                raise APIError('invalid_activation_response') from None
        except APIError as error:
            # A used code can be retried only by this same authenticated installation.
            # Keep transient attempts queued across restarts; discard rejected/expired codes.
            if error.status in (400, 401, 409, 413, 415):
                row.state = {k: v for k, v in row.state.items() if k != 'activation'}
            self.failure(row, 'claim', now, error)
            return
        row.license_cache = {'entitlement': entitlement, 'received_at': now,
                            'checked_at': now, 'server_floor': timestamp(entitlement['server_time'])}
        row.state = {k: v for k, v in row.state.items() if k not in ('activation', 'claim')}
        row.state = dict(row.state, owner_profile_id=profile_id, license={'due': 0}, report={'due': 0})
        row.last_error = ''
        db.session.commit()

    def license(self, row, client, now):
        response = client.request('GET', '/v1/license')
        entitlement = license_response(response, row.installation_id)
        received = time.time()
        if 'station_profile_id' in entitlement:
            row.state = dict(row.state, owner_profile_id=entitlement['station_profile_id'])
        row.license_cache = {'entitlement': entitlement, 'received_at': received,
                            'checked_at': received, 'server_floor': timestamp(entitlement['server_time'])}
        self.success(row, 'license', now, entitlement['refresh_after_seconds'])

    def heartbeat(self, row, client, entries):
        snapshot = machine_snapshot()
        response = client.request('POST', '/v1/heartbeat', {'installation': snapshot, 'stations': entries})
        validate_heartbeat(response, len(entries), sum(len(entry.get('metrics', [])) for entry in entries))
        # Retain only validated, nonsecret acknowledgement fields for operators.
        receipt = {key: response[key] for key in ('server_time', 'next_heartbeat_seconds',
                                                  'stations_accepted', 'metrics_accepted')}
        receipt['freo_version'] = snapshot['freo_version']
        receipt.update(heartbeat_release(response))
        self.save_state(row, last_heartbeat=receipt)
        current_app.logger.info('Central API heartbeat accepted installation=%s server_time=%s stations=%s metrics=%s',
                                row.installation_id, receipt['server_time'],
                                receipt['stations_accepted'], receipt['metrics_accepted'])

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
            self.heartbeat(row, client, entries)
            calls += 1
            heartbeat_sent = True
            for metric in sent:
                metric.sent = True
            self.save_state(row, station_cursor=batch[-1].id)
        # Unknown station observations still allow installation-only reporting.
        if not heartbeat_sent:
            self.heartbeat(row, client, [])
        self.success(row, 'report', now)

    def reserve_calls(self, row, now, count):
        window = int(now // 3600)
        budget = row.state.get('budget', {})
        reserved = budget.get('reserved', 0) if budget.get('hour') == window else 0
        if reserved + count > 90:
            return False
        self.save_state(row, budget={'hour': window, 'reserved': reserved + count})
        return True

    def process_connection_check(self, now=None):
        """Called under the reporter's existing process lock, never by the web app."""
        now = time.time() if now is None else now
        request = db.session.get(CentralConnectionCheck, 1)
        if request is None or request.status not in ('queued', 'checking'):
            return False
        request_id = request.request_id
        if request.status == 'checking':
            # Only one reporter holds the identity lock. A surviving in-flight
            # marker means its previous process stopped before saving the result.
            request.status, request.finished_at = 'failed', now
            request.result = {'message': 'The previous check was interrupted. Please try again.'}
            db.session.commit()
            return True
        request.status, request.started_at = 'checking', now
        db.session.commit()
        try:
            outcome = self.tick(now, manual=True)
            row = installation()
            result = {'freo_version': VERSION}
            if outcome['heartbeat']:
                receipt = row.state['last_heartbeat']
                result.update(heartbeat_release(receipt), version_source='heartbeat',
                              checked_at=receipt['server_time'])
                result['message'] = 'Connected. Heartbeat accepted.'
                if outcome.get('license_error'):
                    result['message'] += ' License refresh unavailable; previous license information retained.'
                status = 'succeeded'
            else:
                status = 'failed'
                error = outcome.get('error') or row.last_error or 'retry_pending'
                messages = {
                    'credentials_rejected': 'Credentials were rejected. Review installation settings.',
                    'credentials_missing_recovery_required': 'Installation credentials need recovery. Review installation settings.',
                    'retry_pending': 'Connection check deferred by the retry schedule.',
                    'rate_limited': 'Connection check deferred by the API request limit.',
                }
                result['message'] = messages.get(error, 'Connection check failed. Previous connection information retained.')
                retry_at = row.state.get('retry_after', 0)
                for name in ('enrollment', 'license', 'report'):
                    state = row.state.get(name, {})
                    if state.get('failures'):
                        retry_at = max(retry_at, state.get('due', 0))
                if error == 'rate_limited':
                    retry_at = max(retry_at, (int(now // 3600) + 1) * 3600)
                result['retry_at'] = retry_at
                # Public discovery is useful even when credentials/enrollment fail.
                # It never proves that an installation heartbeat was accepted.
                if now >= row.state.get('retry_after', 0) and self.reserve_calls(row, now, 1):
                    try:
                        result.update(check_version(current_app.config['FREO_API_URL'], self.client_factory),
                                      version_source='public', checked_at=time.time())
                        result['message'] += ' Public release information refreshed.'
                    except APIError as error:
                        if error.retry_after:
                            retry_at = max(retry_at, now + error.retry_after)
                            self.save_state(row, retry_after=retry_at)
                            result['retry_at'] = retry_at
                        result['message'] += ' Version check unavailable; update status unknown.'
        except Exception as error:
            db.session.rollback()
            status = 'failed'
            result = {'message': 'Connection check unavailable. Please try again.'}
            current_app.logger.warning('Manual connection check failed (%s)', type(error).__name__)
        # Match the request ID so a result can only complete its own request.
        CentralConnectionCheck.query.filter_by(id=1, request_id=request_id).update(
            dict(status=status, finished_at=time.time(), result=result), synchronize_session=False)
        db.session.commit()
        return True

    def tick(self, now=None, manual=False):
        now = time.time() if now is None else now
        outcome = {'heartbeat': False}
        row = installation()
        checkpoint(row, now)
        db.session.commit()
        try:
            credentials = self.register(row)
        except APIError as error:
            row.last_error = error.code
            db.session.commit()
            current_app.logger.warning('Central API registration/storage needs attention (%s)', error.code)
            return dict(outcome, error=error.code)
        if not credentials:
            return outcome
        if row.registration_state == 'credentials_rejected':
            return dict(outcome, error='credentials_rejected')
        self.activate(row, credentials)
        if row.registration_state == 'credentials_rejected':
            return dict(outcome, error='credentials_rejected')
        on_air = sample(now)
        client = self.client_factory(current_app.config['FREO_API_URL'], credentials['access_token'])
        # A process start refreshes the license, while honoring persisted backoff.
        if self.startup and not row.state.get('license', {}).get('failures'):
            self.save_state(row, license={'due': 0})
        self.startup = False
        if manual:
            # Bypass the normal interval, but never a failure backoff, blocked
            # credential or server Retry-After. Normal success schedules the next hour.
            for name in ('license', 'report'):
                state = row.state.get(name, {})
                if not state.get('failures') and not state.get('blocked'):
                    self.save_state(row, **{name: {'due': 0}})
        # Bound total API calls across retries and frequent process restarts.
        if not any(self.due(row, name, now) for name in ('license', 'report')):
            return dict(outcome, error='retry_pending')
        if not self.reserve_calls(row, now, 9):
            return dict(outcome, error='rate_limited')
        for name, operation in [('license', lambda: self.license(row, client, now)),
                                ('report', lambda: self.report(row, client, now, on_air))]:
            if not self.due(row, name, now):
                if manual and name == 'license':
                    outcome['license_error'] = 'retry_pending'
                continue
            try:
                operation()
                if name == 'report':
                    outcome['heartbeat'] = True
            except APIError as error:
                if error.code == 'station_not_synced':
                    for station in Station.query:
                        station_state(station).synced_digest = None
                    db.session.commit()
                    error = APIError('station_not_synced')  # Sync before the next conservative retry.
                self.failure(row, name, now, error)
                outcome['license_error' if name == 'license' else 'error'] = error.code
                if error.status == 401 or error.retry_after:
                    break
        return outcome
