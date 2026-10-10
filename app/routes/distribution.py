"""Installation-only licensing and explicit requests for root-prepared upgrades."""
from functools import wraps
import json
import uuid
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import update
from app.extensions import db
from app.models import AuditEvent, SystemUpgrade
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.software_license import activate, status

distribution = Blueprint('distribution', __name__)


def installation_admin_required(view):
    @admin_required
    @wraps(view)
    def guarded(*args, **kwargs):
        if not current_admin().installation_admin:
            abort(403)
        return view(*args, **kwargs)
    return guarded


@distribution.get('/admin/software')
@installation_admin_required
def page():
    from app.routes.web import admin_stations
    return render_template('admin/software.html', stations=admin_stations(), selected=None,
        page='software', license=status(), upgrades=SystemUpgrade.query.order_by(SystemUpgrade.id).all())


@distribution.post('/admin/software/license')
@installation_admin_required
def activate_license():
    require_csrf()
    try:
        uploaded = request.files.get('license')
        if uploaded is None:
            raise ValueError('Choose the license file supplied by 3andB.')
        raw = uploaded.read(16385)
        if len(raw) > 16384:
            raise ValueError('License file is too large.')
        activate(json.loads(raw), current_admin().id)
    except (ValueError, UnicodeError):
        db.session.rollback()
        abort(400, 'The license could not be verified. Your current license was retained.')
    flash('Unlimited license activated. It works offline across all your installations.', 'success')
    return redirect(url_for('.page'))


@distribution.post('/admin/software/upgrades/<identifier>')
@installation_admin_required
def request_upgrade(identifier):
    require_csrf()
    try:
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError()
    except ValueError:
        abort(404)
    if request.form.get('maintenance') != 'yes':
        abort(400, 'Confirm the maintenance interruption.')
    result = db.session.execute(update(SystemUpgrade).where(SystemUpgrade.id == identifier,
        SystemUpgrade.state == 'prepared').values(state='queued', requested_by=current_admin().id,
        message='Queued. The upgrade runner will verify backup and recovery before migration.'))
    if result.rowcount != 1:
        db.session.rollback()
        abort(409, 'This upgrade is unavailable or has already been requested.')
    db.session.add(AuditEvent(admin_user_id=current_admin().id, action='upgrade.request',
        target_type='system_upgrade', target_id=identifier, summary='Approved prepared upgrade and maintenance interruption'))
    db.session.commit()
    return redirect(url_for('.page'))
