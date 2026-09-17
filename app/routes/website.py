"""Owner-managed station website. Public assets never expose unpublished drafts."""
from copy import deepcopy
import hashlib

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import WebsiteSettings, WebsitePublication, WebsiteAsset
from app.services import website as service
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.admin_media import audit

website = Blueprint('website', __name__)


@website.route('/admin/website', methods=['GET', 'POST'])
@admin_required
def editor():
    from app.routes.web import admin_stations
    row = db.session.get(WebsiteSettings, 1)
    values = service.config(preview=True)
    error = None
    status = 200
    if request.method == 'POST':
        require_csrf()
        try:
            revision = int(request.form.get('revision', '-1'))
            # Compare-and-swap serializes concurrent saves on SQLite and PostgreSQL.
            if row:
                if WebsiteSettings.query.filter_by(id=1, revision=revision).update(
                        {'revision': revision + 1}, synchronize_session=False) != 1:
                    raise ValueError('The website changed in another window. Reload before saving.')
                db.session.refresh(row)
            else:
                if revision != 0:
                    raise ValueError('The website changed. Reload before saving.')
                initial = service.defaults()
                row = WebsiteSettings(id=1, draft=deepcopy(initial), published=deepcopy(initial), revision=1)
                db.session.add(row)
                db.session.flush()
            action = request.form.get('action', 'save')
            if action in ('save', 'publish', 'preview'):
                values = service.validate(request.form, row.draft)
                values = service.upload_assets(request.files, request.form, values)
                row.draft = deepcopy(values)
                if action == 'publish':
                    # Retain the initial public version as a restoration target, too.
                    if not WebsitePublication.query.first():
                        db.session.add(WebsitePublication(config=deepcopy(row.published)))
                    service.publish(row, values)
            elif action == 'discard':
                row.draft = deepcopy(row.published)
            elif action == 'restore':
                publication = db.session.get(WebsitePublication, int(request.form.get('publication', '0')))
                if not publication:
                    raise ValueError('Choose a retained publication')
                row.draft = deepcopy(publication.config)
                service.publish(row, row.draft)
            else:
                raise ValueError('Choose a valid action')
            db.session.flush()
            service.cleanup_assets(row)
            audit('website_' + action, user_id=current_admin().id, target_type='website', target_id='1',
                  summary='Website revision ' + str(row.revision))
            db.session.commit()
            if action == 'preview':
                return redirect(url_for('.preview_frame'), code=303)
            flash('Website published.' if action in ('publish', 'restore') else 'Draft discarded.' if action == 'discard' else 'Draft saved. Your public website has not changed.', 'success')
            return redirect(url_for('.editor'), code=303)
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            error = str(exc) if isinstance(exc, ValueError) else 'The website changed in another window. Reload before saving.'
            status = 409 if 'changed' in error else 400
            # Preserve submitted fields on validation errors. Asset uploads must be reselected.
            values = service.config(preview=True)
            for key in service.TEXT_FIELDS:
                values[key] = request.form.get(key, values[key])
            for key in ('background', 'surface', 'text', 'accent', 'night_background', 'night_surface', 'night_text', 'night_accent', 'focal', 'font', 'theme', 'overlay', 'featured', 'announcement_url', 'announcement_start', 'announcement_end'):
                values[key] = request.form.get(key, values[key])
            values['sections'] = [key for key in request.form.getlist('sections') if key in service.SECTIONS]
            values['socials'] = [dict(label=request.form.get(f'social_label_{i}', ''), url=request.form.get(f'social_url_{i}', '')) for i in range(6)]
            for key in ('show_songs', 'show_artists', 'show_channels', 'show_plays', 'publish_contact'):
                values[key] = request.form.get(key) == 'yes'
            row = db.session.get(WebsiteSettings, 1)
    return render_template('admin/website.html', page='website', selected=None, stations=admin_stations(),
        values=values, revision=request.form.get('revision', '0') if error else row.revision if row else 0,
        error=error, sections=service.SECTIONS, assets=service.ASSETS, channels=service.channels(),
        publications=WebsitePublication.query.order_by(WebsitePublication.id.desc()).all(),
        draft_image=lambda kind: service.image_url(values, kind, True)) , status


@website.get('/admin/website/preview')
@admin_required
def preview():
    response = Response(render_template('home.html', **service.presentation(preview=True)))
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@website.get('/website-assets/<identifier>.png')
def asset(identifier):
    preview = request.args.get('preview') == '1'
    if preview and not current_admin():
        abort(404)
    if identifier not in service.asset_ids(service.config(preview)):
        abort(404)
    row = db.session.get(WebsiteAsset, identifier)
    if not row:
        abort(404)
    small = request.args.get('small') == '1'
    response = Response(row.small if small else row.image, mimetype='image/png')
    response.set_etag(identifier + ('-small' if small else ''))
    response.headers['Cache-Control'] = 'private, no-store' if preview else 'public, max-age=300'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response.make_conditional(request)


@website.get('/website-theme.css')
def theme():
    preview = request.args.get('preview') == '1'
    if preview and not current_admin():
        abort(404)
    values = service.config(preview)
    # Values are validated at publication; fixed keys and hex colors cannot inject CSS.
    import re
    def colors(prefix):
        return ';'.join('--site-'+key+':'+(values[prefix+key] if re.fullmatch(r'#[0-9a-fA-F]{6}', values[prefix+key]) else service.DEFAULTS[prefix+key])
                        for key in ('background', 'surface', 'text', 'accent'))
    initial = 'night_' if values['theme'] == 'night' else ''
    css = '.station-home{' + colors(initial) + '}\n'
    if values['theme'] == 'system':
        css += '@media(prefers-color-scheme:dark){.station-home:not([data-site-theme]){' + colors('night_') + '}}\n'
    shade = max(35, min(80, int(values['overlay']))) / 100
    css += f'.station-home .hero-shade{{background:linear-gradient(90deg,rgba(0,0,0,{min(.9, shade+.2)}),rgba(0,0,0,{shade/2})),linear-gradient(0deg,rgba(0,0,0,.5),transparent 40%)}}\n'
    css += '.station-home[data-site-theme="day"]{' + colors('') + '}\n.station-home[data-site-theme="night"]{' + colors('night_') + '}\n'
    response = Response(css, mimetype='text/css')
    response.set_etag(hashlib.sha256(css.encode()).hexdigest())
    response.headers['Cache-Control'] = 'private, no-store' if preview else 'public, max-age=0, must-revalidate'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response.make_conditional(request)


@website.get('/admin/website/preview-frame')
@admin_required
def preview_frame():
    return render_template('admin/website_preview.html')
