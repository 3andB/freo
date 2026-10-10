"""Offline, owner-wide perpetual licenses; no network or machine binding."""
import base64
import json
from pathlib import Path
import uuid
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import current_app
from app.extensions import db
from app.models import SoftwareLicense, AuditEvent

KEYS = Path(__file__).resolve().parents[1] / 'data/license-keys.json'


def signing_bytes(payload):
    return b'Freo perpetual license v1\n' + json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def verify(document):
    try:
        if not isinstance(document, dict) or set(document) != {'payload', 'signature', 'key_id'}:
            raise ValueError()
        keys = current_app.config.get('FREO_LICENSE_PUBLIC_KEYS')
        if keys is None:
            keys = json.loads(KEYS.read_text())
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[document['key_id']], validate=True))
        payload = document['payload']
        key.verify(base64.b64decode(document['signature'], validate=True), signing_bytes(payload))
        if set(payload) != {'license_id', 'owner', 'issued_at', 'product', 'edition', 'updates', 'installations', 'expires'}:
            raise ValueError()
        uuid.UUID(payload['license_id'])
        if (payload['product'] != 'Freo' or payload['edition'] != 'unlimited' or payload['updates'] != 'all-future'
                or payload['installations'] != 'all-owned' or payload['expires'] is not None
                or not isinstance(payload['owner'], str) or not 1 <= len(payload['owner'].strip()) <= 254):
            raise ValueError()
        from datetime import datetime
        datetime.fromisoformat(payload['issued_at'])
        return payload
    except (ValueError, TypeError, KeyError, AttributeError, InvalidSignature, OSError) as error:
        raise ValueError('This license cannot be verified by this Freo release.') from error


def status():
    row = db.session.get(SoftwareLicense, 1)
    if row is None:
        return {'edition': 'community'}
    try:
        return verify(row.document)
    except ValueError:
        return {'edition': 'community', 'error': 'Saved license needs review; existing broadcasts are unaffected.'}


def unlimited():
    return status()['edition'] == 'unlimited'


def activate(document, user_id=None):
    payload = verify(document)
    row = db.session.get(SoftwareLicense, 1)
    if row is None:
        db.session.add(SoftwareLicense(id=1, document=document))
    else:
        row.document = document
    db.session.add(AuditEvent(admin_user_id=user_id, action='software_license.activate',
        target_type='installation', target_id='1', summary='Activated perpetual unlimited license ' + payload['license_id']))
    db.session.commit()
    return payload
