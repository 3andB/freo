"""Read-only release discovery, independent of identity and licensing."""
import re

from app.version import VERSION
from .client import APIError, Client


_SEMVER = re.compile(
    r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
    r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
)


def semver_key(value):
    """SemVer 2.0.0 precedence (https://semver.org/#spec-item-11).

    Numeric identifiers sort by length then digits, avoiding integer size limits.
    Build metadata is validated but never included in precedence.
    """
    match = _SEMVER.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError('Invalid semantic version')
    core = tuple((len(part), part) for part in match.group(1, 2, 3))
    prerelease = match.group(4)
    identifiers = []
    for part in prerelease.split('.') if prerelease is not None else ():
        numeric = part.isdigit()
        if numeric and len(part) > 1 and part.startswith('0'):
            raise ValueError('Invalid semantic version')
        identifiers.append((0, len(part), part) if numeric else (1, 0, part))
    return core, prerelease is None, tuple(identifiers)


def heartbeat_release(response):
    """Optional fields must not invalidate an otherwise accepted heartbeat."""
    latest = response.get('latest_version')
    try:
        semver_key(latest)
    except ValueError:
        latest = None
    available = response.get('update_available')
    return dict(latest_version=latest,
                update_available=available if type(available) is bool else None)


def check_version(base_url, client_factory=Client):
    # No identity store, enrollment, entitlement, or database access is needed.
    response = client_factory(base_url).request('GET', '/v1/releases/latest')
    try:
        latest = response['latest_version']
        available = semver_key(latest) > semver_key(VERSION)
    except (KeyError, TypeError, ValueError):
        raise APIError('invalid_release_response') from None
    return dict(freo_version=VERSION, latest_version=latest, update_available=available)
