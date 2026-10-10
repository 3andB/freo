"""Server-owned version status and optional public release metadata."""
import re

from app.version import VERSION
from .client import APIError, Client, timestamp

STATUS_LABELS = {'CURRENT': 'Current', 'UPDATE_AVAILABLE': 'Update Available',
                 'AHEAD': 'Ahead', 'UNKNOWN': 'Unknown'}


def version_string(value):
    # Legacy strings and leading-v/prerelease identities are opaque to the client.
    return value if isinstance(value, str) and value.strip() and len(value) <= 128 else None


def heartbeat_release(response):
    """Optional fields never invalidate an otherwise accepted heartbeat."""
    latest = version_string(response.get('latest_version'))
    status = response.get('version_status')
    if not isinstance(status, str) or status not in STATUS_LABELS or latest is None:
        status = 'UNKNOWN'
    available = response.get('update_available')
    if status == 'UNKNOWN' or type(available) is not bool:
        available = None
    elif (status == 'UPDATE_AVAILABLE') != available:
        available = None  # An inconsistent boolean must not generate a notice.
    return dict(installed_version=version_string(response.get('installed_version')),
                latest_version=latest, version_status=status, update_available=available)


def release_link(value):
    if isinstance(value, str) and re.fullmatch(
            r'https://github\.com/3andB/freo/releases/tag/[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', value):
        return value
    return None


def discovery_time(value):
    # Legacy client caches used a numeric local fetch time here. Never relabel it
    # as the mothership's successful release-discovery timestamp.
    try:
        timestamp(value)
        return value
    except (TypeError, ValueError, OverflowError):
        return None


def check_version(base_url, client_factory=Client):
    # Public discovery cannot establish how this installation compares to latest.
    response = client_factory(base_url).request('GET', '/v1/releases/latest')
    latest = version_string(response.get('latest_version'))
    if 'latest_version' not in response or (response['latest_version'] is not None and latest is None):
        raise APIError('invalid_release_response')
    checked = discovery_time(response.get('checked_at'))
    return dict(freo_version=VERSION, latest_version=latest, version_status='UNKNOWN',
                update_available=None, checked_at=checked,
                release_url=release_link(response.get('release_url')) if latest else None)


def version_view(state, now, *, manual=None):
    """Shared UI projection; never performs network I/O or version comparisons."""
    receipt = state.get('last_heartbeat', {})
    version = heartbeat_release(receipt)
    contact = receipt.get('server_time')
    try:
        contact_at = timestamp(contact)
        age = now - contact_at
        stale = not 0 <= age <= receipt.get('next_heartbeat_seconds', 3600) + 300
    except (TypeError, ValueError, OverflowError):
        contact_at, stale = 0, True
    newer_check = bool(manual and (manual.finished_at or 0) >= contact_at)
    failed_check = newer_check and manual.status == 'failed'
    public_result = (manual.result if newer_check and manual.result.get('version_source') == 'public' else None)
    stale = stale or bool(state.get('report', {}).get('failures')) or failed_check
    changed = receipt.get('freo_version') != VERSION
    if changed:
        version.update(version_status='UNKNOWN', update_available=None)
    source = 'Heartbeat' if contact else 'Not yet checked'
    discovery = state.get('release_discovery', {})
    if public_result is not None:
        if public_result.get('latest_version') != version.get('latest_version'):
            version.update(version_status='UNKNOWN', update_available=None)
        version['latest_version'] = public_result.get('latest_version')
        discovery = public_result
        source = 'Public release discovery'
    status = version['version_status']
    note = ('Awaiting a heartbeat for the running version.' if changed and contact else
            'Last known status; contact is stale. Retrying through the existing reporter.' if stale and contact else
            'Awaiting the first successful heartbeat.' if not contact else '')
    latest = version.get('latest_version')
    matching_release = latest is not None and discovery.get('latest_version') == latest
    return dict(installed_version=VERSION, latest_version=latest or 'Unknown',
                version_status=status, update_status=STATUS_LABELS[status],
                update_available=version.get('update_available'), version_note=note,
                version_source=source, version_checked_at=contact or 'Not yet checked',
                release_checked_at=discovery_time(discovery.get('checked_at')) or 'Unknown',
                release_url=release_link(discovery.get('release_url')) if matching_release else None)
