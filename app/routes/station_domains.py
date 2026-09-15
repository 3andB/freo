"""Station settings domain mutations using the existing global-admin boundary."""
from flask import Blueprint, abort, flash, redirect, request, url_for
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import StationDomain
from app.routes.web import station_or_404
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.admin_media import audit
from app.services import station_domains as domains
from app.services.stations import allocation_lock

station_domains = Blueprint('station_domains', __name__)


@station_domains.post('/admin/stations/<slug>/domains/<action>')
@admin_required
def mutate(slug, action):
    require_csrf()
    if action not in {'add', 'verify', 'primary', 'remove'}:
        abort(404)
    allocation_lock()
    station = station_or_404(slug, require_enabled=False)
    try:
        if action == 'add':
            row = domains.add_domain(station, request.form.get('hostname', ''))
        else:
            domain_id = request.form.get('domain_id', type=int)
            if domain_id is None or not 1 <= domain_id <= 2147483647:
                abort(404)
            row = StationDomain.query.filter_by(station_id=station.id, id=domain_id).first_or_404()
            if action == 'verify':
                domains.verify_domain(row)
            elif action == 'primary':
                domains.set_primary(row)
            else:
                db.session.delete(row)
        audit('station_domain_' + action, user_id=current_admin().id, station_id=station.id,
              target_type='station_domain', target_id=str(row.id), summary=row.hostname)
        db.session.commit()
        flash('Domain ' + {'add': 'added. Follow the DNS instructions to verify it.', 'verify': 'verified and enabled.',
                          'primary': 'set as primary.', 'remove': 'removed.'}[action], 'success')
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        flash(str(error) if isinstance(error, ValueError) else 'That hostname or primary assignment is already in use. Refresh and retry.', 'error')
    return redirect(url_for('station_settings.page', slug=station.slug) + '#domains', code=303)
