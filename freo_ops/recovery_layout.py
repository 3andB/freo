"""Narrow, restart-safe filesystem operations for live recovery."""
import grp
import os
from pathlib import Path
import re
import stat
import tempfile

from .hosting import HostingError
from .upgrade import sync_directory


def managed_directory(path):
    """Create only the final directory, through trusted non-symlink ancestors."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise HostingError('invalid_configuration', 'Unsafe recovery directory.')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            final = index == len(path.parts) - 2
            if final:
                try: os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise HostingError('invalid_configuration', 'Unsafe recovery directory ownership or permissions.')
            if final:
                os.fchown(fd, 0, 0)
                os.fchmod(fd, 0o755)
                os.fsync(fd)
        sync_directory(path.parent)
    except OSError as exc:
        raise HostingError('invalid_configuration', 'Unsafe recovery directory.') from exc
    finally:
        os.close(fd)


def atomic_file(destination, data, mode, *, group=None):
    """Replace a regular file without following a destination symlink."""
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise HostingError('invalid_configuration', 'Unsafe recovery file destination.')
    fd, temporary = tempfile.mkstemp(prefix='.freo-recovery-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if group is not None: os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), mode)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, destination)
        sync_directory(destination.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def launcher_bytes(data, source, release):
    """Relocate only a generated entry point's interpreter, never its body."""
    original = (str(source) + '/venv/bin/').encode()
    relocated = (str(release) + '/venv/bin/').encode()
    # pip/distlib uses this exact shell trampoline for long interpreter paths.
    if data.startswith(b"#!/bin/sh\n'''exec' "):
        pattern = rb"\A(#!/bin/sh\n'''exec' )([^\n]+)(\n)"
        match = re.match(pattern, data)
        command = match[2] if match else b''
        quoted = command.startswith(b'"')
        prefix = b'"' if quoted else b''
        if command.startswith(prefix + original):
            end = command.find(b'"' if quoted else b' ', len(prefix))
            if end < 0: return data
            interpreter = command[len(prefix):end]
            if re.fullmatch(re.escape(original) + rb'python[0-9.]*', interpreter):
                return data[:match.start(2)] + prefix + relocated + interpreter[len(original):] + command[end:] + data[match.end(2):]
        return data
    first, separator, body = data.partition(b'\n')
    match = re.fullmatch(rb'(#![ \t]*)([^ \t\r]+)([^\r]*)(\r?)', first)
    if match and re.fullmatch(re.escape(original) + rb'python[0-9.]*', match[2]):
        first = match[1] + relocated + match[2][len(original):] + match[3] + match[4]
    return first + separator + body


def relocate_launchers(verified_bin, destination_bin, source, release):
    # Always read immutable verified restore input, including after interruption.
    for original in sorted(Path(verified_bin).iterdir()):
        if original.is_symlink() or not original.is_file(): continue
        data = original.read_bytes()
        if not data.startswith(b'#!'): continue
        relocated = launcher_bytes(data, source, release)
        atomic_file(Path(destination_bin) / original.name, relocated,
                    stat.S_IMODE(original.stat().st_mode))


def canonical_environment(source, destination):
    source, destination = Path(source), Path(destination)
    from .hosting import trusted
    trusted(source)
    # Validate parent independently; never follow an unsafe existing target.
    for parent in (destination.parent, *destination.parent.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise HostingError('invalid_configuration', 'Unsafe configuration directory.')
    atomic_file(destination, source.read_bytes(), 0o640, group=grp.getgrnam('freo').gr_gid)


def sync_tree(path):
    """Persist copied contents and directory entries before recording attachment."""
    path = Path(path)
    entries = [path, *path.rglob('*')] if path.is_dir() and not path.is_symlink() else [path]
    directories = []
    for entry in entries:
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            continue
        if stat.S_ISDIR(info.st_mode):
            directories.append(entry)
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
            try: os.fsync(fd)
            finally: os.close(fd)
        else:
            raise HostingError('invalid_configuration', 'Unsupported recovery file type.')
    for directory in reversed(directories):
        sync_directory(directory)
    sync_directory(path.parent)


def attach_verified_copy(source, staged, target):
    """A checkpoint may trust target only after its verified copy is durable."""
    import shutil
    from . import recovery
    source, staged, target = map(Path, (source, staged, target))
    if staged.parent.stat().st_dev != target.parent.stat().st_dev or target.exists() or target.is_symlink():
        raise HostingError('invalid_configuration', 'Unsafe recovery attachment destination.')
    if staged.exists() or staged.is_symlink():
        if staged.is_dir() and not staged.is_symlink(): shutil.rmtree(staged)
        else: staged.unlink()
    recovery.run(['cp', '-a', '--', str(source), str(staged)])
    sync_tree(staged)
    os.rename(staged, target)
    sync_directory(target.parent)
    if staged.parent != target.parent:
        sync_directory(staged.parent)


def atomic_symlink(destination, value):
    """Keep an existing link until its complete replacement can be committed."""
    import uuid
    destination = Path(destination)
    temporary = destination.parent / ('.freo-link-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(value)
        os.replace(temporary, destination)
        sync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)
