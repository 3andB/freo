"""Explicit public directory actions. No credentials, automatic publication or sync."""
import http.client
import ipaddress
import json
import random
import re
import ssl
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import dns.resolver
from flask import current_app
from sqlalchemy import update

from app.extensions import db
from app.models import Station
from app.services.admin_media import audit
from app.services.station_domains import addresses, preferred_url


def public_url(value):
    """Only configured, credential-free public HTTP(S) destinations may be shared."""
    try:
        url = urlsplit(value)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment
                or re.search(r'[\s\\\x00-\x1f\x7f]', value)):
            raise ValueError()
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError()
        host = url.hostname.rstrip('.')
        try:
            ips = {ipaddress.ip_address(host)}
        except ValueError:
            if '.' not in host or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid', '.example')):
                raise ValueError()
            ips = addresses(host)
        if not ips or any(not ip.is_global for ip in ips):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Configure a public HTTP(S) URL without credentials or private addresses before listing.') from None
    return value


def metadata(station):
    from app.services.stations import validate_slug
    if (not station.enabled or not station.stream or not station.stream.enabled
            or station.deleted_at or station.lifecycle_state != 'ready'):
        raise ValueError('The station and stream must be enabled and ready before listing.')
    validate_slug(station.slug)
    if station.public_slug:
        validate_slug(station.public_slug)
    name = (station.name or '').strip()
    if not name or len(name) > 400 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a valid station name before listing.')
    base = current_app.config.get('PUBLIC_BASE_URL', '').rstrip('/')
    public_url(base)
    if urlsplit(base).path:
        raise ValueError('PUBLIC_BASE_URL must contain only the public origin.')
    result = {'name': name, 'url': base + station.stream.public_path,
              'homepage': public_url(preferred_url(station))}
    if station.logo:
        result['favicon'] = base + '/station-assets/' + station.slug + '/logo.png'
    if station.country:
        if not re.fullmatch('[A-Z]{2}', station.country):
            raise ValueError('Use a two-letter uppercase country code before listing.')
        result['countrycode'] = station.country
    tags = [station.genre, *(station.directory_categories or [])]
    tags = list(dict.fromkeys(tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()))
    if tags:
        result['tags'] = ','.join(tags)
    return result


def radio_browser_server():
    # Radio Browser documents SRV discovery; never pin a single mirror.
    rows = dns.resolver.resolve('_api._tcp.radio-browser.info.', 'SRV', lifetime=3, search=False)
    hosts = [str(row.target).rstrip('.').lower() for row in rows]
    hosts = [host for host in hosts if re.fullmatch(r'[a-z0-9-]+\.api\.radio-browser\.info', host)]
    if not hosts:
        raise ValueError('No Radio Browser server is available.')
    return random.choice(hosts)


class SubmissionUncertain(Exception):
    pass


class SubmissionRejected(Exception):
    pass


def radio_browser_add(host, payload):
    connection = http.client.HTTPSConnection(host, timeout=5, context=ssl.create_default_context())
    sent = False
    try:
        connection.connect()
        connection.sock.settimeout(10)
        sent = True
        connection.request('POST', '/json/add', body=urlencode(payload), headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'Freo/1.0 (freo.world)',
            'Accept': 'application/json'})
        response = connection.getresponse()
        raw = response.read(16385)
        if len(raw) > 16384 or response.status != 200:
            raise SubmissionUncertain()
        data = json.loads(raw)
        if isinstance(data, dict) and data.get('ok') is False:
            raise SubmissionRejected()
        if not isinstance(data, dict) or data.get('ok') is not True:
            raise SubmissionUncertain()
        return str(UUID(data['uuid']))
    except (SubmissionRejected, SubmissionUncertain):
        raise
    except Exception as error:
        if sent:
            raise SubmissionUncertain() from error
        raise
    finally:
        connection.close()


def submit_radio_browser(station, user):
    if station.radio_browser_uuid:
        raise ValueError('This station is already listed in Radio Browser.')
    if station.radio_browser_status not in ('not_listed', 'error'):
        raise ValueError('Submission is already in progress or needs operator reconciliation.')
    try:
        payload = metadata(station)
    except ValueError as error:
        db.session.execute(update(Station).where(Station.id == station.id,
            Station.radio_browser_uuid.is_(None), Station.radio_browser_status.in_(('not_listed', 'error'))
            ).values(radio_browser_status='error', radio_browser_error=str(error)[:240]))
        db.session.commit()
        raise
    # Commit a durable claim before the external side effect. No playback or
    # installation-wide database lock is held during network I/O.
    claimed = db.session.execute(update(Station).where(Station.id == station.id,
        Station.radio_browser_uuid.is_(None), Station.radio_browser_status.in_(('not_listed', 'error')),
        Station.enabled.is_(True), Station.deleted_at.is_(None), Station.lifecycle_state == 'ready'
        ).values(radio_browser_status='submitting', radio_browser_error=''))
    if claimed.rowcount != 1:
        db.session.rollback()
        raise ValueError('Submission is already in progress or needs operator reconciliation.')
    db.session.commit()
    try:
        identifier = radio_browser_add(radio_browser_server(), payload)
    except Exception as error:
        uncertain = isinstance(error, SubmissionUncertain)
        station.radio_browser_status = 'uncertain' if uncertain else 'error'
        station.radio_browser_error = ('Submission outcome is unknown. Check Radio Browser and reconcile the listing before submitting again.'
            if uncertain else 'Radio Browser could not accept the submission. Check station settings and try again.')
        current_app.logger.warning('Radio Browser submission failed: station_id=%s error_type=%s', station.id, type(error).__name__)
        db.session.commit()
        raise ValueError(station.radio_browser_error) from None
    station.radio_browser_uuid = identifier
    station.radio_browser_status = 'listed'
    station.radio_browser_error = ''
    audit('radio_browser_listed', user_id=user.id, station_id=station.id,
          target_type='station', target_id=station.slug, summary='Station submitted to Radio Browser')
    # If this commit fails the durable claim prevents a second remote insertion.
    db.session.commit()


def queue_internet_radio(station, enabled, user):
    from app.services.stations import allocation_lock
    if enabled:
        metadata(station)
    allocation_lock()
    db.session.refresh(station)
    if station.internet_radio_status in ('pending', 'applying'):
        raise ValueError('A directory setting change is already in progress.')
    if enabled:
        if not station.enabled or station.deleted_at or station.lifecycle_state != 'ready':
            raise ValueError('The station must be enabled and ready before listing.')
        # Icecast advertises /<internal-slug>; static Flask routes take priority.
        if any(rule.rule.rstrip('/') == '/' + station.slug for rule in current_app.url_map.iter_rules()):
            raise ValueError('This station mount conflicts with a public page and cannot use YP advertising.')
    if station.internet_radio_enabled == enabled and station.internet_radio_status == 'ready':
        return False
    station.internet_radio_pending = enabled
    station.internet_radio_status = 'pending'
    station.internet_radio_error = ''
    audit('internet_radio_requested', user_id=user.id, station_id=station.id,
          target_type='station', target_id=station.slug, summary='Internet-Radio.com listing ' + ('enabled' if enabled else 'disabled'))
    return True
