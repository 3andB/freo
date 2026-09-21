"""Authoritative installation preferences; secrets stay in bootstrap config."""
import ipaddress
import os
from urllib.parse import urlsplit
from flask import current_app
from sqlalchemy import select, update, text
from app.extensions import db
from app.models import InstallationSettings, AuditEvent

DEFAULTS = {
    'PUBLIC_BASE_URL': '', 'FREO_DOMAIN': '', 'FREO_INSTALLATION_HOSTS': '',
    'FREO_DOMAIN_TARGET_HOST': '', 'FREO_DOMAIN_TARGET_IPS': '',
    'FREO_MAX_STATIONS': 3, 'MAX_MEDIA_UPLOAD_BYTES': 128 * 1024 * 1024,
    'MAX_MEDIA_BATCH_BYTES': 512 * 1024 * 1024, 'FREO_LIVE_MIC': False,
}


class SettingsUnavailable(RuntimeError):
    pass


def validate(values):
    if set(values) - set(DEFAULTS):
        raise ValueError('Unknown installation setting')
    merged = dict(DEFAULTS, **values)
    for key in ('FREO_MAX_STATIONS', 'MAX_MEDIA_UPLOAD_BYTES', 'MAX_MEDIA_BATCH_BYTES'):
        if type(merged[key]) is not int:
            raise ValueError(key + ' must be an integer')
    if merged['FREO_MAX_STATIONS'] < 0:
        raise ValueError('FREO_MAX_STATIONS cannot be negative')
    if not 1024 * 1024 <= merged['MAX_MEDIA_UPLOAD_BYTES'] <= 128 * 1024 * 1024:
        raise ValueError('Upload limit must be between 1 and 128 MiB')
    if not merged['MAX_MEDIA_UPLOAD_BYTES'] <= merged['MAX_MEDIA_BATCH_BYTES'] <= 1024 * 1024 * 1024:
        raise ValueError('Batch limit must be at least the file limit and at most 1 GiB')
    if type(merged['FREO_LIVE_MIC']) is not bool:
        raise ValueError('FREO_LIVE_MIC must be a boolean')
    for key in ('PUBLIC_BASE_URL', 'FREO_DOMAIN', 'FREO_INSTALLATION_HOSTS',
                'FREO_DOMAIN_TARGET_HOST', 'FREO_DOMAIN_TARGET_IPS'):
        if not isinstance(merged[key], str) or len(merged[key]) > 4096:
            raise ValueError(key + ' must be text of at most 4096 characters')
    from app.services.station_domains import normalize_hostname
    if merged['PUBLIC_BASE_URL']:
        url = urlsplit(merged['PUBLIC_BASE_URL'])
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('PUBLIC_BASE_URL must be an HTTP(S) origin without credentials')
        normalize_hostname(url.netloc)
    for key in ('FREO_DOMAIN', 'FREO_DOMAIN_TARGET_HOST'):
        if merged[key]:
            normalize_hostname(merged[key])
    for host in merged['FREO_INSTALLATION_HOSTS'].split(','):
        if host.strip():
            normalize_hostname(host.strip())
    for address in merged['FREO_DOMAIN_TARGET_IPS'].split(','):
        if address.strip():
            ipaddress.ip_address(address.strip())
    return merged


def legacy_values(*, validated=True):
    values = {key: current_app.config.get(key, default) for key, default in DEFAULTS.items()}
    values['FREO_LIVE_MIC'] = os.environ.get('FREO_LIVE_MIC', '0') == '1'
    return validate(values) if validated else values


def snapshot():
    row = db.session.execute(select(InstallationSettings.values, InstallationSettings.revision)
                             .where(InstallationSettings.id == 1)).first()
    if row is None:
        if current_app.testing:
            return legacy_values(validated=False), 0
        raise SettingsUnavailable('Installation settings have not been adopted; run flask settings import-environment')
    return validate(row[0]), row[1]


def get_setting(key):
    if key not in DEFAULTS:
        raise KeyError(key)
    return snapshot()[0][key]


def import_environment():
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(717304022)'))
    row = db.session.execute(select(InstallationSettings).where(InstallationSettings.id == 1)
                             .with_for_update()).scalar_one_or_none()
    if row:
        missing = set(DEFAULTS) - set(row.values)
        if not missing:
            db.session.commit()
            return False
        row.values = dict(row.values, **{key: DEFAULTS[key] for key in missing})
        row.revision += 1
    else:
        db.session.add(InstallationSettings(id=1, values=legacy_values(), revision=1))
    db.session.add(AuditEvent(action='settings.import', target_type='installation', target_id='1',
                             summary='Imported missing installation settings; existing values preserved'))
    db.session.commit()
    return True


def set_setting(key, value, expected_revision):
    if key not in DEFAULTS:
        raise ValueError('Unknown installation setting')
    values, revision = snapshot()
    if not revision or revision != expected_revision:
        raise ValueError('Settings changed or are not initialized; read the current revision first')
    values[key] = value
    values = validate(values)
    result = db.session.execute(update(InstallationSettings).where(
        InstallationSettings.id == 1, InstallationSettings.revision == expected_revision
    ).values(values=values, revision=expected_revision + 1))
    if result.rowcount != 1:
        db.session.rollback()
        raise ValueError('Settings changed; read the current revision first')
    db.session.add(AuditEvent(action='settings.update', target_type='installation', target_id='1',
                             summary='Updated installation setting ' + key))
    db.session.commit()
    return expected_revision + 1
