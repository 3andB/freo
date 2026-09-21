"""Small, preserving Icecast 2.5 YP configuration patch and apply operation."""
from app.services.installation_settings import get_setting
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from flask import current_app

from app.extensions import db
from app.models import Station
from app.services import station_runtime as runtime
from app.services.radio_directories import metadata

# Internet-Radio.com's HTTPS endpoint redirects to its forum, not its YP
# service. The documented HTTP endpoint speaks YP; no credentials are sent.
YP_URL = 'http://icecast-yp.internet-radio.com'
SOCKET_ID = 'freo-directory-public'


class DirectoryRecoveryError(RuntimeError):
    pass


def parse_config(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Icecast configuration must not contain XML entities.')
    root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != 'icecast':
        raise ValueError('Invalid Icecast configuration root.')
    return root


def set_text(parent, name, value):
    nodes = parent.findall(name)
    if len(nodes) > 1:
        raise ValueError('Ambiguous Icecast configuration.')
    node = nodes[0] if nodes else ET.SubElement(parent, name)
    node.text = value


def directory_config(raw, station, enabled):
    """Patch only advertising settings, preserving credentials and other config."""
    root = parse_config(raw)
    directories = root.findall('directory') + root.findall('yp-directory')
    managed = [node for node in directories if node.tag == 'yp-directory'
               and node.get('url') == YP_URL
               and any(option.get('name') == 'listen-socket' and option.get('value') == '#' + SOCKET_ID
                       for option in node.findall('option'))]
    if len(managed) > 1 or (enabled and len(directories) != len(managed)):
        raise ValueError('Other Icecast YP directories are configured. Resolve them before enabling this integration.')
    sockets = root.findall(f"listen-socket[@id='{SOCKET_ID}']")
    if len(sockets) > 1 or (sockets and not managed):
        raise ValueError('Conflicting directory listener configuration.')
    mounts = root.findall('mount')
    targets = [mount for mount in mounts if mount.findtext('mount-name') == '/' + station.slug]
    if len(targets) != 1:
        raise ValueError('Station Icecast mount is missing or ambiguous. Provision the station first.')
    target = targets[0]
    if enabled:
        from app.services.station_domains import normalize_hostname
        data = metadata(station)
        origin = urlsplit(get_setting('PUBLIC_BASE_URL'))
        if origin.scheme != 'https':
            raise ValueError('Internet-Radio.com requires a configured public HTTPS origin.')
        normalize_hostname(origin.hostname, domain=True)
        contact = root.findtext('admin', '')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact) or contact.lower().endswith(('.local', '.localhost', '.internal', '.invalid', '.test')):
            raise ValueError('Configure a public technical contact email in the Icecast admin setting before enabling YP.')
        if not data.get('tags'):
            raise ValueError('Set the station genre or directory categories before enabling YP.')
        if target.find('cluster-password') is not None:
            raise ValueError('Remove the mount YP cluster password before enabling this integration.')
        # Replace the bootstrap hostname with the public host required by YP.
        hostname = root.findtext('hostname', '')
        if hostname == 'localhost' or '.' not in hostname:
            set_text(root, 'hostname', origin.hostname)
        if not managed:
            # A source's Ice-Public header must never opt another mount in.
            for mount in mounts:
                set_text(mount, 'public', '0')
            if not any(mount.get('type') == 'default' for mount in mounts):
                default = ET.SubElement(root, 'mount', {'type': 'default'})
                set_text(default, 'public', '0')
            listener = ET.SubElement(root, 'listen-socket', {'id': SOCKET_ID, 'type': 'virtual'})
            set_text(listener, 'bind-address', origin.hostname)
            set_text(listener, 'port', str(origin.port or 443))
            set_text(listener, 'tls', 'rfc2818')
            directory = ET.SubElement(root, 'yp-directory', {'url': YP_URL})
            ET.SubElement(directory, 'option', {'name': 'timeout', 'value': '15'})
            ET.SubElement(directory, 'option', {'name': 'listen-socket', 'value': '#' + SOCKET_ID})
        else:
            if len(sockets) != 1:
                raise ValueError('Directory listener is missing.')
            if (sockets[0].findtext('bind-address') != origin.hostname
                    or sockets[0].findtext('port') != str(origin.port or 443)):
                if any(mount.findtext('public') == '1' for mount in mounts):
                    raise ValueError('Public origin changed. Disable existing YP listings before changing the directory origin.')
                set_text(sockets[0], 'bind-address', origin.hostname)
                set_text(sockets[0], 'port', str(origin.port or 443))
        for name, value in (('stream-name', data['name']), ('stream-description', station.description or ''),
                            ('stream-url', data['homepage']), ('genre', data['tags']),
                            ('bitrate', str(station.stream.bitrate))):
            set_text(target, name, value)
    set_text(target, 'public', '1' if enabled else '0')
    # Keep the dormant directory when the last mount opts out: removing the
    # directory itself makes Icecast discard its SID before sending YP remove.
    # Explicit public=0 (including the default mount) prevents new advertising.
    candidate = ET.tostring(root, encoding='utf-8')
    validate_config(candidate)
    # Compare normalized XML so repeated application does not reload.
    return raw if candidate == ET.tostring(parse_config(raw), encoding='utf-8') else candidate


def validate_config(raw):
    """XML and semantic validation of the supported managed configuration.

    Icecast has no dry-run CLI. The real 2.5 parser and SIGHUP behavior are
    additionally covered by the isolated engine test, never a live restart.
    """
    root = parse_config(raw)
    directory = root.find(f"yp-directory[@url='{YP_URL}']")
    if directory is None:
        return
    listener = root.find(f"listen-socket[@id='{SOCKET_ID}']")
    if (listener is None or listener.get('type') != 'virtual' or listener.findtext('tls') != 'rfc2818'
            or not listener.findtext('bind-address') or not 1 <= int(listener.findtext('port', '0')) <= 65535):
        raise ValueError('Invalid directory listener.')
    if {node.get('name'): node.get('value') for node in directory.findall('option')} != {
            'timeout': '15', 'listen-socket': '#' + SOCKET_ID}:
        raise ValueError('Invalid YP options.')
    defaults = root.findall("mount[@type='default']")
    if len(defaults) != 1 or defaults[0].findtext('public') != '0':
        raise ValueError('Unconfigured mounts must not advertise.')
    seen = set()
    for mount in root.findall('mount'):
        name = mount.findtext('mount-name')
        if mount.get('type') != 'default':
            if not name or name in seen:
                raise ValueError('Ambiguous mount configuration.')
            seen.add(name)
        if mount.findtext('public') not in ('0', '1'):
            raise ValueError('Every mount must explicitly opt in or out.')
        if mount.findtext('public') == '1' and mount.find('cluster-password') is not None:
            raise ValueError('YP credentials must not be published.')


def apply_config(candidate):
    """Return previous bytes for transaction recovery; reload only on change."""
    path = runtime.ROOT / 'radio/icecast.xml'
    previous = path.read_bytes()
    validate_config(candidate)
    if candidate == previous:
        return None
    staged = runtime.atomic_install(path, candidate.decode('utf-8'), 0o640, 'root', 'icecast')
    try:
        os.replace(staged, path)
        runtime.run_checked(['/bin/systemctl', 'reload', 'icecast2.service'])
    except Exception:
        try:
            restore_config(previous)
        except Exception as error:
            raise DirectoryRecoveryError() from error
        raise
    finally:
        staged.unlink(missing_ok=True)
    return previous


def restore_config(previous):
    path = runtime.ROOT / 'radio/icecast.xml'
    staged = runtime.atomic_install(path, previous.decode('utf-8'), 0o640, 'root', 'icecast')
    os.replace(staged, path)
    runtime.run_checked(['/bin/systemctl', 'reload', 'icecast2.service'])


def process_pending_directories():
    runtime.require_root()
    ids = [row.id for row in Station.query.filter(Station.internet_radio_status.in_(('pending', 'applying')))]
    failures = []
    for identifier in ids:
        previous = None
        with runtime.operation_lock():
            station = db.session.get(Station, identifier)
            db.session.refresh(station)
            if station.internet_radio_status not in ('pending', 'applying'):
                continue
            try:
                enabled = station.internet_radio_pending
                if type(enabled) is not bool:
                    raise ValueError('Invalid pending directory setting.')
                station.internet_radio_status = 'applying'
                db.session.commit()
                candidate = directory_config((runtime.ROOT / 'radio/icecast.xml').read_bytes(), station, enabled)
                previous = apply_config(candidate)
                station.internet_radio_enabled = enabled
                station.internet_radio_pending = None
                station.internet_radio_status = 'ready'
                station.internet_radio_error = ''
                db.session.commit()
            except Exception as error:
                db.session.rollback()
                recovery_failed = isinstance(error, DirectoryRecoveryError)
                if previous is not None:
                    try:
                        restore_config(previous)
                    except Exception:
                        recovery_failed = True
                station.internet_radio_status = 'failed'
                station.internet_radio_error = ('Directory configuration recovery failed. Check the provisioning service.' if recovery_failed else
                    str(error) if isinstance(error, ValueError) else 'Directory change failed. Check the provisioning service and retry.')[:240]
                db.session.commit()
                current_app.logger.error('Internet-Radio.com apply failed: station_id=%s error_type=%s', identifier, type(error).__name__)
                failures.append(identifier)
    return failures
