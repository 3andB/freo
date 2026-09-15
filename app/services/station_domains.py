"""Verified public host routing. Hosts select public content, never permissions."""
import ipaddress
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

import dns.exception
import dns.resolver
from flask import abort, current_app, g, render_template, request, url_for

from app.extensions import db
from app.models import StationDomain
from app.services.stations import public_station_for


def normalize_hostname(value, *, domain=False):
    if not isinstance(value, str) or not value or not value.isascii() or re.search(r'[\s/@\\?#,]', value):
        raise ValueError('Enter a hostname only, using ASCII or IDNA punycode')
    # Bracketed IPv6 is valid for explicitly configured installation access only.
    if value.startswith('['):
        match = re.fullmatch(r'\[([0-9a-fA-F:]+)\](?::([0-9]{1,5}))?', value)
        if not match or domain:
            raise ValueError('Invalid hostname')
        host, port = match.groups()
        host = '[' + str(ipaddress.IPv6Address(host)) + ']'
    else:
        match = re.fullmatch(r'([^:]+)(?::([0-9]{1,5}))?', value)
        if not match:
            raise ValueError('Invalid hostname')
        host, port = match.groups()
        host = host.lower().removesuffix('.')
        if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
            raise ValueError('Invalid hostname')
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError('Invalid port')
    if domain:
        if '.' not in host or host.rsplit('.', 1)[-1].isdigit():
            raise ValueError('Use a fully qualified domain name, not an IP address')
    return host


def installation_hosts():
    config = current_app.config
    values = config.get('FREO_INSTALLATION_HOSTS', '').split(',')
    values += [config.get('FREO_DOMAIN', ''), urlsplit(config.get('PUBLIC_BASE_URL', '')).netloc]
    if current_app.testing or current_app.debug:
        values += ['localhost', '127.0.0.1', '[::1]']
    return {normalize_hostname(value.strip()) for value in values if value.strip()}


def add_domain(station, hostname):
    hostname = normalize_hostname(hostname, domain=True)
    if hostname in installation_hosts():
        raise ValueError('The installation hostname cannot be assigned to a station')
    if StationDomain.query.filter_by(hostname=hostname).first():
        raise ValueError('That hostname is already claimed')
    row = StationDomain(station_id=station.id, hostname=hostname, verification_token=secrets.token_hex(32))
    db.session.add(row)
    db.session.flush()
    return row


def dns_records(hostname, kind):
    """Absolute DNS queries, at most three seconds each; no HTTP requests."""
    try:
        return list(dns.resolver.resolve(hostname + '.', kind, lifetime=3, search=False))
    except dns.resolver.NoAnswer:
        return []
    except dns.exception.DNSException as error:
        raise ValueError('DNS lookup failed or timed out; check records and retry') from error


def addresses(hostname):
    return {ipaddress.ip_address(row.address) for kind in ('A', 'AAAA') for row in dns_records(hostname, kind)}


def verify_domain(row):
    config = current_app.config
    try:
        expected = {ipaddress.ip_address(value.strip()) for value in config.get('FREO_DOMAIN_TARGET_IPS', '').split(',') if value.strip()}
    except ValueError as error:
        raise ValueError('The operator must configure valid domain target IP addresses') from error
    target = config.get('FREO_DOMAIN_TARGET_HOST', '').strip()
    if target:
        expected |= addresses(normalize_hostname(target, domain=True))
    if not expected:
        raise ValueError('The operator must configure domain verification targets first')
    actual = addresses(row.hostname)
    if not actual or not actual <= expected:
        raise ValueError('All A/AAAA addresses must point to this Freo installation')
    challenge = ('freo-verification=' + row.verification_token).encode('ascii')
    if not any(b''.join(record.strings) == challenge for record in dns_records('_freo-verification.' + row.hostname, 'TXT')):
        raise ValueError('The station-specific verification TXT record is missing or incorrect')
    row.verified_at = datetime.now(timezone.utc)
    row.enabled = True


def set_primary(row):
    if not row.enabled or not row.verified_at:
        raise ValueError('Verify this domain before making it primary')
    StationDomain.query.filter_by(station_id=row.station_id, is_primary=True).update({'is_primary': False})
    db.session.flush()
    row.is_primary = True


def preferred_url(station):
    primary = StationDomain.query.filter_by(station_id=station.id, enabled=True, is_primary=True).filter(StationDomain.verified_at.isnot(None)).first()
    if primary:
        return 'https://' + primary.hostname + '/'
    base = current_app.config.get('PUBLIC_BASE_URL', '').rstrip('/')
    return base + url_for('web.player', slug=station.public_slug or station.slug)


def route_public_host():
    endpoints = {'web.homepage', 'web.stations', 'web.player', 'web.listen_alias', 'station_settings.logo'}
    if request.endpoint not in endpoints:
        return None
    try:
        hostname = normalize_hostname(request.environ.get('HTTP_HOST', ''))
    except ValueError:
        abort(400)
    if hostname in installation_hosts():
        return None
    row = StationDomain.query.filter_by(hostname=hostname, enabled=True).filter(StationDomain.verified_at.isnot(None)).first()
    station = row.station if row else None
    if not station or not station.enabled or station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'):
        abort(404)
    g.domain_station = station
    if request.endpoint in {'web.homepage', 'web.stations'}:
        return render_template('player.html', station=station)
    try:
        path_station = public_station_for(request.view_args['slug'])
    except ValueError:
        path_station = None
    if not path_station or path_station.id != station.id:
        abort(404)
    return None
