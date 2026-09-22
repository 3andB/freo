"""Versioned first-use agreement, recorded in the existing durable audit log."""
from app.models import AuditEvent


AGREEMENT_VERSION = '2026-09-22-source-available-1'
AGREEMENT_URL = 'https://freo.live/licensing'


def acceptance_for(user):
    return AuditEvent.query.filter_by(
        admin_user_id=user.id, action='license.accept',
        target_type='license_agreement', target_id=AGREEMENT_VERSION,
    ).first()


def agreement_context():
    from app.services.admin_auth import current_admin
    user = current_admin()
    return dict(version=AGREEMENT_VERSION, url=AGREEMENT_URL,
                required=bool(user and not acceptance_for(user)))
