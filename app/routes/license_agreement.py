"""Explicit, authenticated acceptance of the first-use license agreement."""
from flask import Blueprint, abort, jsonify, redirect, request, url_for

from app.extensions import db
from app.models import AuditEvent
from app.services.admin_auth import current_admin, media_mutation_required
from app.services.license_agreement import AGREEMENT_VERSION, acceptance_for, agreement_context


license_agreement = Blueprint('license_agreement', __name__)


@license_agreement.app_context_processor
def template_helpers():
    return {'license_agreement_context': agreement_context}


@license_agreement.post('/admin/license-agreement/accept')
@media_mutation_required
def accept():
    if request.form.get('version') != AGREEMENT_VERSION or request.form.get('agree') != 'yes':
        abort(400)
    user = current_admin()
    if not acceptance_for(user):
        db.session.add(AuditEvent(
            admin_user_id=user.id, action='license.accept',
            target_type='license_agreement', target_id=AGREEMENT_VERSION,
            summary='Accepted Freo license agreement and copyright broadcasting restriction.',
        ))
        db.session.commit()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(accepted=True, version=AGREEMENT_VERSION)
    return redirect(url_for('web.admin_home'))
