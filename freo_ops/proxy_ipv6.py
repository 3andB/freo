"""Narrow migration of Freo's wildcard HTTP/HTTPS listeners to both families."""
import os
from pathlib import Path
import re
import tempfile

from .recovery import RecoveryError, run

TEMPLATES = {
    'deploy/nginx/freo.conf.template',
    'deploy/nginx/custom-domain.conf.template',
    'deploy/nginx/reject-unknown.conf',
}
LISTEN = re.compile(r'^(?P<indent>[ \t]*)listen (?P<port>80|443)(?P<flags>(?: [a-z0-9_]+)*);(?P<comment>[^\n]*)$', re.M)


def with_ipv6(body):
    """Preserve all routing/TLS text; refuse ambiguous custom listener layouts."""
    matches = list(LISTEN.finditer(body))
    ports = [match['port'] for match in matches]
    if len(ports) != len(set(ports)):
        raise RecoveryError('Multiple proxy server blocks share a port; review IPv6 listeners manually')
    if not matches:
        raise RecoveryError('No standard wildcard proxy listener; review IPv6 listeners manually')
    additions = {}
    for match in matches:
        port, flags = match['port'], match['flags']
        existing = re.findall(r'^\s*listen \[([^]]+)\]:'+port+r'([^;]*);', body, re.M)
        if existing:
            if existing != [('::', flags)]:
                raise RecoveryError('Customized IPv6 proxy listener needs manual review')
            continue
        additions[match.start()] = '\n'+match['indent']+'listen [::]:'+port+flags+';'
    return LISTEN.sub(lambda match: match[0]+additions.get(match.start(), ''), body)


def allowed_template_change(relative, old, new):
    if str(relative) not in TEMPLATES:
        return False
    try:
        return old != new and with_ipv6(old) == new
    except RecoveryError:
        return False


def plan(directory=Path('/etc/nginx/sites-available')):
    """Include enabled Freo vhosts; preserve unrelated sites and saved copies."""
    changes = {}
    enabled = directory.with_name('sites-enabled')
    active = {path.resolve() for path in enabled.iterdir()} if enabled.exists() else set()
    reject = (Path(__file__).resolve().parents[1] / 'deploy/nginx/reject-unknown.conf').read_text()
    old_reject = '\n'.join(line for line in reject.split('\n') if 'listen [::]:' not in line)
    for path in sorted(directory.iterdir()) if directory.exists() else ():
        if not path.is_file() or path.resolve() not in active:
            continue
        body = path.read_text()
        if (body not in (reject, old_reject)
                and ('include /etc/nginx/snippets/freo-stream.conf;' not in body
                     or 'proxy_pass http://127.0.0.1:8000;' not in body)):
            if path.name == 'freo':
                raise RecoveryError('Customized primary proxy site needs manual review')
            continue
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise RecoveryError('Proxy migration requires root-owned regular configuration files')
        changed = with_ipv6(body)
        if changed != body:
            changes[path] = (body, changed)
    return changes


def replace(path, body):
    original = path.stat()
    fd, temporary = tempfile.mkstemp(prefix='.freo-ipv6-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), original.st_uid, original.st_gid)
            os.fchmod(stream.fileno(), original.st_mode & 0o777)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(changes):
    if not changes:
        return
    for path, (before, _) in changes.items():
        if path.is_symlink() or path.read_text() != before:
            raise RecoveryError('Proxy configuration changed after preflight')
    written = []
    try:
        for path, (before, after) in changes.items():
            replace(path, after)
            written.append((path, before))
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    except Exception:
        for path, before in reversed(written):
            replace(path, before)
        raise
