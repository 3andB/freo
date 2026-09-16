"""Public intake and global-admin review using the existing auth boundary."""
from flask import Blueprint, abort, render_template, request, redirect, url_for
from app.extensions import db
from app.models import DMCACase
from app.services.admin_auth import admin_required, media_mutation_required, require_csrf, current_admin
from app.services.admin_media import audit
from app.services.dmca import FIELDS, STATUSES, RateLimited, submit

dmca = Blueprint('dmca', __name__)


@dmca.before_request
def bound_request():
    request.max_content_length = 32 * 1024


@dmca.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@dmca.route('/dmca', methods=['GET', 'POST'])
def report():
    error = None
    status = 200
    values = {key: request.args.get(key, '')[:limit] for key, _, limit, _ in FIELDS}
    if request.method == 'POST':
        require_csrf()
        values = request.form
        try:
            case = submit(request.form)
            return render_template('dmca.html', reference=case.reference), 201
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
            status = 429 if isinstance(exc, RateLimited) else 400
    response = render_template('dmca.html', fields=FIELDS, values=values, error=error)
    return response, status, {'Retry-After': '3600'} if status == 429 else {}


@dmca.get('/admin/dmca')
@admin_required
def cases():
    rows = db.paginate(db.select(DMCACase).order_by(DMCACase.created_at.desc(), DMCACase.id.desc()), per_page=30, max_per_page=30)
    return render_template('admin/dmca.html', cases=rows, page='dmca', stations=[], selected=None)


@dmca.get('/admin/dmca/<reference>')
@admin_required
def detail(reference):
    row = DMCACase.query.filter_by(reference=reference).first_or_404()
    return render_template('admin/dmca.html', case=row, statuses=STATUSES, page='dmca', stations=[], selected=None)


@dmca.post('/admin/dmca/<reference>/status')
@media_mutation_required
def status(reference):
    row = DMCACase.query.filter_by(reference=reference).with_for_update().first_or_404()
    value = request.form.get('status')
    if value not in STATUSES:
        abort(400)
    if row.status != value:
        audit('dmca_status_changed', user_id=current_admin().id, station_id=row.station_id,
              target_type='dmca_case', target_id=row.reference, summary=f'{row.status} → {value}')
        row.status = value
        db.session.commit()
    return redirect(url_for('dmca.detail', reference=row.reference))
