"""Browser-only credential administration using existing ADMIN and CSRF rules."""
from flask import Blueprint, abort, render_template, request, redirect, url_for

from app.extensions import db
from app.models import ApiCredential, Station
from app.services.admin_auth import admin_required, current_admin, csrf_token, require_csrf
from app.services import public_api as service

api_credentials = Blueprint('api_credentials', __name__)


@api_credentials.after_request
def private(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@api_credentials.route('/admin/api-credentials', methods=['GET', 'POST'])
@admin_required
def page():
    user = current_admin()
    if user.role != 'ADMIN':
        abort(403)
    token, error = None, None
    if request.method == 'POST':
        require_csrf()
        try:
            _, token = service.create_credential(user, request.form.get('name', ''),
                request.form.getlist('stations'), request.form.get('scope', 'read'))
            db.session.commit()
        except ValueError as exception:
            db.session.rollback()
            error = str(exception)
    stations = service.station_query().order_by(Station.name, Station.id).all()
    credentials = ApiCredential.query.order_by(ApiCredential.created_at.desc(), ApiCredential.id).all()
    return render_template('admin/api_credentials.html', selected=None, stations=stations,
        page='api-credentials', credentials=credentials, token=token, error=error, csrf=csrf_token()), 400 if error else 200


@api_credentials.post('/admin/api-credentials/<identifier>/revoke')
@admin_required
def revoke(identifier):
    if current_admin().role != 'ADMIN':
        abort(403)
    require_csrf()
    row = db.session.get(ApiCredential, identifier)
    if row is None:
        abort(404)
    service.revoke_credential(current_admin(), row)
    db.session.commit()
    return redirect(url_for('api_credentials.page'))
