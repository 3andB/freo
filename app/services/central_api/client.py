"""Pinned wire contract: freo-live/api/docs/contract.md at 1116c05.

No automatic transport retries: registration is deliberately non-idempotent.
"""
import http.client
import json
import re
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID

MAX_BYTES = 256 * 1024


class APIError(Exception):
    def __init__(self, code, *, status=0, retry_after=0):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


def timestamp(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('Invalid API timestamp')
    parsed = datetime.fromisoformat(value[:-1] + '+00:00')
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Invalid API timestamp')
    return parsed.timestamp()


def uuid_string(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Invalid API UUID')
    return value


def identity_response(data):
    try:
        uuid_string(data['installation_id'])
        if not re.fullmatch(r'freo_[A-Za-z0-9_-]{43}', data['access_token']):
            raise ValueError()
        if data['token_type'] != 'Bearer' or data['heartbeat_interval_seconds'] != 3600:
            raise ValueError()
        timestamp(data['server_time'])
        return {key: data[key] for key in ('installation_id', 'access_token')}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise APIError('invalid_registration_response') from None


def license_response(data, installation_id):
    try:
        if uuid_string(data['installation_id']) != installation_id:
            raise ValueError()
        if not isinstance(data['plan'], str) or not data['plan'].strip():
            raise ValueError()
        if type(data['channel_limit']) is not int or not 1 <= data['channel_limit'] <= 10000:
            raise ValueError()
        if data['status'] not in ('active', 'suspended', 'expired'):
            raise ValueError()
        issued, server, grace = (timestamp(data[key]) for key in ('issued_at', 'server_time', 'grace_until'))
        if issued > server or grace < issued:
            raise ValueError()
        for key in ('expires_at', 'renews_at'):
            if data[key] is not None:
                timestamp(data[key])
        if data['outage_policy'] != 'keep_existing_stations_on_air':
            raise ValueError()
        if type(data['refresh_after_seconds']) is not int or not 60 <= data['refresh_after_seconds'] <= 86400:
            raise ValueError()
        keys = ('installation_id', 'plan', 'channel_limit', 'status', 'issued_at', 'expires_at',
                'renews_at', 'grace_until', 'server_time', 'refresh_after_seconds', 'outage_policy')
        result = {key: data[key] for key in keys}
        if 'station_profile_id' in data:
            result['station_profile_id'] = uuid_string(data['station_profile_id']) if data['station_profile_id'] is not None else None
        if 'registration_status' in data:
            expected = 'registered' if result.get('station_profile_id') else 'unregistered'
            if 'station_profile_id' not in result or data['registration_status'] != expected:
                raise ValueError()
            result['registration_status'] = expected
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise APIError('invalid_license_response') from None


class Client:
    def __init__(self, base_url='https://api.freo.live', token=None):
        self.url = urlsplit(base_url)
        if (self.url.scheme != 'https' or not self.url.hostname or self.url.username or self.url.password
                or self.url.query or self.url.fragment or self.url.path not in ('', '/')):
            raise ValueError('Central API must be an HTTPS origin')
        self.token = token

    def request(self, method, path, payload=None):
        if path not in ('/v1/enroll', '/v1/register', '/v1/activate', '/v1/stations/sync', '/v1/heartbeat', '/v1/license'):
            raise ValueError('Unknown central API endpoint')
        body = None if payload is None else json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
        if body is not None and len(body) > MAX_BYTES:
            raise APIError('payload_too_large', status=413)
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        connection = http.client.HTTPSConnection(self.url.hostname, self.url.port or 443,
                                                 timeout=5, context=ssl.create_default_context())
        try:
            connection.connect()
            connection.sock.settimeout(30)
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_BYTES + 1)
            if not 200 <= response.status < 300:
                retry = response.getheader('Retry-After', '')
                try:
                    retry = int(retry) if retry.isdigit() else max(0, int(
                        (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()))
                except (ValueError, TypeError, OverflowError):
                    retry = 0
                # Never log response bodies, URLs, headers or exception strings.
                code = 'unauthorized' if response.status == 401 else 'http_' + str(response.status)
                if response.status == 409:
                    try:
                        candidate = json.loads(raw)['error']['code']
                        if candidate in ('station_not_synced', 'station_conflict'):
                            code = candidate
                    except (ValueError, KeyError, TypeError):
                        pass
                raise APIError(code, status=response.status, retry_after=max(0, retry))
            if len(raw) > MAX_BYTES:
                raise APIError('response_too_large')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise APIError('invalid_response')
            return data
        except APIError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise APIError('connection_or_response_error') from None
        finally:
            connection.close()
