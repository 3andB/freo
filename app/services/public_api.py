"""Credential lifecycle and atomic limits; no broadcast mutations."""
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
import time

from flask import current_app, request
from sqlalchemy import delete

from app.extensions import db
from app.models import ApiCredential, ApiCredentialStation, ApiRateBucket, Station
from app.services.admin_auth import can_access_station
from app.services.admin_media import audit

TOKEN_PATTERN = re.compile(r'freo_v1_([0-9a-f]{32})\.([A-Za-z0-9_-]{43})\Z')


def station_query():
    return Station.query.filter(Station.deleted_at.is_(None),
        Station.lifecycle_state.notin_(('pending_delete', 'delete_failed')))


def create_credential(user, name, station_ids, scope='read'):
    if not user or not user.active or user.role != 'ADMIN' or user.setup_required:
        raise PermissionError('Administrator access required')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError('Enter a name of 1 to 120 characters.')
    if scope != 'read':
        raise ValueError('Only read scope is supported.')
    try:
        ids = {int(identifier) for identifier in station_ids}
    except (ValueError, TypeError):
        raise ValueError('Choose valid stations.') from None
    stations = station_query().filter(Station.id.in_(ids)).all()
    if not ids or len(stations) != len(ids) or any(not can_access_station(user, s) for s in stations):
        raise ValueError('Choose one or more authorized stations.')
    identifier, secret = secrets.token_hex(16), secrets.token_urlsafe(32)
    token = f'freo_v1_{identifier}.{secret}'
    row = ApiCredential(id=identifier, name=name.strip(), scope=scope, created_by=user.id,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        grants=[ApiCredentialStation(station_id=s.id) for s in stations])
    db.session.add(row)
    audit('api_credential_created', user_id=user.id, target_type='api_credential', target_id=identifier,
          summary='Read access to station IDs: ' + ', '.join(str(s.id) for s in stations))
    return row, token


def revoke_credential(user, row):
    if not user or not user.active or user.role != 'ADMIN' or user.setup_required:
        raise PermissionError('Administrator access required')
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        audit('api_credential_revoked', user_id=user.id, target_type='api_credential', target_id=row.id)


def authenticate(header):
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    token = parts[1]
    match = TOKEN_PATTERN.fullmatch(token)
    if not match:
        return None
    row = db.session.get(ApiCredential, match[1])
    digest = hashlib.sha256(token.encode()).hexdigest()
    valid = hmac.compare_digest(row.token_digest if row else '0' * 64, digest)
    if not valid or not row or row.revoked_at or row.scope != 'read':
        return None
    owner = row.creator
    if not owner or not owner.active or owner.role != 'ADMIN' or owner.setup_required:
        return None
    return row


def rate_limit(kind, key, limit, now=None):
    """An independent transaction never commits application or scheduler state."""
    now = time.time() if now is None else now
    minute = int(now) // 60
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
    table = ApiRateBucket.__table__
    statement = insert(table).values(kind=kind, key=key, minute=minute, count=1)
    statement = statement.on_conflict_do_update(
        index_elements=['kind', 'key', 'minute'],
        set_={'count': table.c.count + 1}, where=table.c.count < limit).returning(table.c.count)
    with db.engine.begin() as connection:
        connection.execute(delete(table).where(table.c.minute < minute - 1440))
        allowed = connection.execute(statement).scalar_one_or_none() is not None
    return allowed, max(1, 60 - int(now) % 60)


def network_key(now=None):
    now = time.time() if now is None else now
    address = request.remote_addr or 'unknown'
    if address in current_app.config.get('DMCA_TRUSTED_PROXY_IPS', ()):
        address = request.headers.get('X-Real-IP', address)
    return hmac.new(current_app.secret_key.encode(),
        f'public-api:{int(now) // 86400}:{address}'.encode(), hashlib.sha256).hexdigest()
