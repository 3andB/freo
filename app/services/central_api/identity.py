"""Worker-only atomic credential storage. Never included in database exports/UI."""
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
import fcntl
from .client import APIError, uuid_string


class IdentityStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'identity.json'

    def prepare(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise APIError('unsafe_credential_directory')

    @contextmanager
    def lock(self):
        self.prepare()
        fd = os.open(self.directory / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise APIError('worker_already_running') from None
            yield
        finally:
            os.close(fd)

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise APIError('unsafe_credential_file')
            with os.fdopen(fd, 'r') as stream:
                fd = None
                data = json.loads(stream.read(4096))
            if data == {'registration_attempted': True}:
                return data
            uuid_string(data['installation_id'])
            if not re.fullmatch(r'freo_[A-Za-z0-9_-]{43}', data['access_token']):
                raise ValueError()
            return data
        except (ValueError, KeyError, TypeError):
            raise APIError('invalid_credential_file') from None
        finally:
            if fd is not None:
                os.close(fd)

    def write(self, data):
        self.prepare()
        fd, filename = tempfile.mkstemp(prefix='.identity-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(filename, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(filename):
                os.unlink(filename)
