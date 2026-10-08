"""Byte accounting and crash-safe reservations shared by media writers.

Reservations are files, not entitlements. A live flock owns each reservation;
crashed writers' files remain accounted by the filesystem scan.
"""
from contextlib import contextmanager
import fcntl
from functools import wraps
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from . import hosting

ROOT = Path('/var/lib/freo-hosting-storage')
INVENTORY = Path('/etc/freo/hosting-storage.json')


def inventory():
    hosting.trusted(INVENTORY)
    value = json.loads(INVENTORY.read_text())
    if not isinstance(value.get('roots'), list) or not value['roots']:
        raise hosting.HostingError('storage_unavailable', 'Hosting storage inventory is unavailable.')
    return value


def files_usage(roots):
    seen = set()
    total = 0
    def visit(path):
        nonlocal total
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise hosting.HostingError('storage_unavailable', 'Symlinked customer media requires administrator review.')
        identity = (info.st_dev, info.st_ino)
        if identity in seen:
            return
        seen.add(identity)
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
        elif stat.S_ISDIR(info.st_mode):
            for entry in path.iterdir():
                visit(entry)
        else:
            raise hosting.HostingError('storage_unavailable', 'Non-regular customer media requires administrator review.')
    for root in roots:
        visit(Path(root))
    return total


def blob_usage(config):
    import psycopg2
    # Dedicated local read-only role, peer authenticated. No credentials in policy.
    import pwd
    with psycopg2.connect(dbname=config['database'], user=pwd.getpwuid(os.geteuid()).pw_name,
                          host=config['socket'], connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            total = 0
            from psycopg2 import sql
            for table, columns in config['blobs'].items():
                for column in columns:
                    cursor.execute(sql.SQL('SELECT COALESCE(sum(octet_length({})),0) FROM {}').format(sql.Identifier(column), sql.Identifier(table)))
                    total += cursor.fetchone()[0]
            return total


@contextmanager
def locked():
    fd = os.open(ROOT / 'lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def outstanding():
    total = 0
    for path in ROOT.glob('reservation-*'):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                data = os.read(fd, 1024)
                total += int(data)
            else:
                path.unlink(missing_ok=True)
        finally:
            os.close(fd)
    return total


def usage():
    policy = hosting.read()
    if not policy['hosted']:
        return {'hosted': False}
    try:
        config = inventory()
        with locked():
            files = files_usage(config['roots'])
            blobs = blob_usage(config)
            reserved = outstanding()
        limit = policy['limits']['storage_gb'] * 1_000_000_000
        used = files + blobs
        return dict(used_bytes=used, file_bytes=files, database_media_bytes=blobs,
                    reserved_bytes=reserved, limit_bytes=limit, remaining_bytes=max(0, limit-used-reserved),
                    percent=round(100*used/limit, 2), over_quota=used>limit)
    except hosting.HostingError:
        raise
    except Exception:
        raise hosting.HostingError('storage_unavailable', 'Storage accounting is unavailable; new media writes are restricted.') from None


@contextmanager
def reserve(amount):
    policy = hosting.require_service()
    if not policy['hosted']:
        yield
        return
    if type(amount) is not int or amount < 0:
        raise ValueError('Invalid storage reservation')
    fd = None
    name = None
    try:
        config = inventory()
        with locked():
            policy = hosting.require_service()
            used = files_usage(config['roots']) + blob_usage(config)
            reserved = outstanding()
            limit = policy['limits']['storage_gb'] * 1_000_000_000
            if used + reserved + amount > limit:
                raise hosting.HostingError('storage_limit_exceeded', 'Media storage is full. Delete media or increase storage capacity.', used_bytes=used, requested_bytes=amount, limit_bytes=limit)
            devices = set()
            for root in config['roots']:
                path = Path(root)
                while not path.exists():
                    path = path.parent
                device = path.stat().st_dev
                if device in devices:
                    continue
                devices.add(device)
                disk = shutil.disk_usage(path)
                if disk.free - reserved - amount < max(1_000_000_000, disk.total // 20):
                    raise hosting.HostingError('disk_reserve', 'Media writes are paused to preserve system disk capacity.')
            fd, name = tempfile.mkstemp(prefix='reservation-', dir=ROOT)
            os.fchmod(fd, 0o660)
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, str(amount).encode()); os.fsync(fd)
        yield
    finally:
        if name:
            Path(name).unlink(missing_ok=True)
        if fd is not None:
            os.close(fd)


def bounded(amount):
    """Reserve a proven upper bound; callers must enforce that output bound."""
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if not hosting.read()['hosted']:
                return function(*args, **kwargs)
            size = amount(*args, **kwargs) if callable(amount) else amount
            with reserve(size):
                return function(*args, **kwargs)
        return wrapper
    return decorate


def write(stream, data):
    with reserve(len(data)):
        result = stream.write(data)
        stream.flush()
        return result


def run_media(args, *, max_output_bytes, **kwargs):
    """Kernel-bounded subprocess output; never uses preexec_fn in threaded workers."""
    import subprocess
    if not hosting.read()['hosted']:
        return subprocess.run(args, **kwargs)
    with reserve(max_output_bytes):
        return subprocess.run(['/usr/bin/prlimit', '--fsize='+str(max_output_bytes), '--', *args], **kwargs)
