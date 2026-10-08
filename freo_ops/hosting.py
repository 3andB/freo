"""Root-controlled hosting policy. Standard library only; never uses customer settings."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

CONFIG = Path('/etc/freo/hosting.json')
STATE = Path('/var/lib/freo-hosting')
PLANS = {
    'starter': dict(stations=3, listeners=100, bitrate_kbps=128, storage_gb=25),
    'pro': dict(stations=10, listeners=250, bitrate_kbps=128, storage_gb=50),
}
STATUSES = ('active', 'past_due', 'suspended', 'maintenance')


class HostingError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def response(self):
        return dict(success=False, error=self.code, message=str(self), **self.details)


def validate(value):
    if not isinstance(value, dict) or type(value.get('hosted')) is not bool:
        raise HostingError('invalid_configuration', 'Hosting configuration requires a boolean hosted field.')
    if not value['hosted']:
        if set(value) != {'hosted'}:
            raise HostingError('invalid_configuration', 'Self-hosted configuration accepts only hosted=false.')
        return dict(hosted=False)
    if set(value) - {'hosted', 'plan', 'status', 'limits', 'reason'} or not {'plan', 'status', 'limits'} <= value.keys():
        raise HostingError('invalid_configuration', 'Hosting configuration fields are invalid.')
    if value['plan'] not in (*PLANS, 'custom') or value['status'] not in STATUSES:
        raise HostingError('invalid_configuration', 'Unknown hosting plan or service status.')
    limits = value['limits']
    if not isinstance(limits, dict) or set(limits) != set(PLANS['starter']):
        raise HostingError('invalid_configuration', 'All four hosting limits are required.')
    for key, number in limits.items():
        if type(number) is not int or not 1 <= number <= 1_000_000:
            raise HostingError('invalid_configuration', 'Hosting limits must be positive integers no greater than 1000000.', field=key)
    if limits['listeners'] > 32640:
        raise HostingError('invalid_configuration', 'Listener allowance exceeds the supported Icecast capacity.')
    if limits['bitrate_kbps'] < 64:
        raise HostingError('invalid_configuration', 'Maximum bitrate must allow at least 64 kbps.')
    reason = value.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 160 or any(ord(c) < 32 for c in reason):
        raise HostingError('invalid_configuration', 'Reason must be plain text of at most 160 characters.')
    return dict(value, limits=dict(limits))


def trusted(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise HostingError('invalid_configuration', 'Hosting policy permissions are unsafe.')
    if not path.is_file():
        raise HostingError('invalid_configuration', 'Hosting policy must be a regular file.')


def read():
    try:
        if not CONFIG.exists() and not CONFIG.is_symlink():
            if (STATE / 'enabled').exists():
                raise HostingError('invalid_configuration', 'Hosted configuration is missing; service is restricted.')
            return {'hosted': False}
        trusted(CONFIG)
        if CONFIG.stat().st_size > 8192:
            raise HostingError('invalid_configuration', 'Hosting configuration is too large.')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('duplicate field')
                result[key] = value
            return result
        value = validate(json.loads(CONFIG.read_text(), object_pairs_hook=pairs))
        if (STATE / 'enabled').exists() and not value['hosted']:
            raise HostingError('invalid_configuration', 'Hosting cannot be disabled by replacing its configuration.')
        return value
    except HostingError:
        raise
    except (OSError, ValueError, TypeError):
        raise HostingError('invalid_configuration', 'Hosting configuration cannot be read; service is restricted.') from None


def require_service():
    policy = read()
    if policy['hosted'] and (policy['status'] in ('suspended', 'maintenance') or (STATE / 'inhibit').exists()):
        raise HostingError('service_unavailable', 'Hosting service is suspended or undergoing maintenance.', status=policy['status'])
    return policy


def check_bitrate(bitrate):
    policy = read()
    if policy['hosted'] and bitrate > policy['limits']['bitrate_kbps']:
        raise HostingError('bitrate_limit_exceeded', 'Requested bitrate exceeds the hosting allowance.', requested_bitrate=bitrate, limit=policy['limits']['bitrate_kbps'])


def check_stations(count, *, adding=False):
    policy = require_service()
    if policy['hosted'] and count + int(adding) > policy['limits']['stations']:
        limit = policy['limits']['stations']
        raise HostingError('station_limit_exceeded', f'Your hosting plan supports {limit} stations. Upgrade your plan to add more.', current_stations=count, requested_limit=limit)
    return policy


def atomic(path, value, mode=0o644):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, sort_keys=True); output.write('\n')
            output.flush(); os.fsync(output.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def administrative_lock():
    if os.geteuid() != 0:
        raise HostingError('unauthorized', 'Root authorization is required.')
    STATE.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd = os.open(STATE / 'admin.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
