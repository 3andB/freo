"""Bearer-only, read-only access to root-approved installation materials."""
import hashlib
import hmac
import time

from flask import Blueprint, current_app, g, jsonify, request, send_file, url_for

from app.services import public_api as limits
from freo_ops import studio_access as access

studio_releases = Blueprint('studio_releases', __name__, url_prefix='/api/studio')


def _error(code, status):
    response = jsonify(error=code)
    response.status_code = status
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="Freo Studio releases"'
    return response


def _is_studio():
    return request.path == '/api/studio' or request.path.startswith('/api/studio/')


def _https():
    # Gunicorn binds loopback; bundled Nginx overwrites this header with $scheme.
    return request.is_secure or (request.remote_addr in ('127.0.0.1', '::1')
                                 and request.headers.get('X-Forwarded-Proto') == 'https')


def init_studio_api(app):
    @app.before_request
    def authenticate_studio():
        if not _is_studio():
            return None
        if not _https():
            return _error('https_required', 403)
        day = int(time.time()) // 86400
        address = request.remote_addr or 'unknown'
        if address in current_app.config.get('DMCA_TRUSTED_PROXY_IPS', ()):
            address = request.headers.get('X-Real-IP', address)
        network = hmac.new(current_app.secret_key.encode(),
                           f'studio:{day}:{address}'.encode(), hashlib.sha256).hexdigest()
        allowed, retry = limits.rate_limit('studio-network', network, 60)
        if not allowed:
            response = _error('rate_limited', 429)
            response.headers['Retry-After'] = str(retry)
            return response
        try:
            identifier = access.authenticate(request.headers.get('Authorization', ''))
        except access.AccessError:
            current_app.logger.error('Studio key inventory unavailable')
            return _error('unavailable', 503)
        if identifier is None:
            return _error('unauthorized', 401)
        allowed, retry = limits.rate_limit('studio-key', identifier, 120)
        if not allowed:
            response = _error('rate_limited', 429)
            response.headers['Retry-After'] = str(retry)
            return response
        if request.endpoint == 'studio_releases.download':
            allowed, retry = limits.rate_limit('studio-download', identifier, 12)
            if not allowed:
                response = _error('rate_limited', 429)
                response.headers['Retry-After'] = str(retry)
                return response
        g.studio_key_id = identifier

    @app.after_request
    def studio_headers(response):
        if _is_studio():
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            current_app.logger.info('Studio API method=%s endpoint=%s status=%s key=%s remote=%s',
                                    request.method, request.endpoint or 'unmatched', response.status_code,
                                    getattr(g, 'studio_key_id', 'none'), request.remote_addr)
        return response

    app.register_blueprint(studio_releases)


@studio_releases.errorhandler(access.AccessError)
def invalid_release(error):
    current_app.logger.warning('Studio staged material unavailable (%s)', type(error).__name__)
    return _error('unavailable', 503)


@studio_releases.get('/health')
def health():
    for row in access.catalog().values():
        for role in access.ROLES:
            access.artifact(row, role)
    return jsonify(status='ok')


@studio_releases.get('/releases')
def releases():
    rows = access.catalog()
    for row in rows.values():
        for role in access.ROLES:
            access.artifact(row, role)
    return jsonify(releases=[{'version': version, 'manifest': url_for('.manifest', version=version)}
                            for version in sorted(rows)])


@studio_releases.get('/releases/<version>/manifest')
def manifest(version):
    row = access.catalog().get(version)
    if row is None:
        return _error('not_found', 404)
    materials = {}
    for role in access.ROLES:
        _, entry = access.artifact(row, role)
        materials[role] = dict(name=entry['name'], size=entry['size'], sha256=entry['sha256'],
                               download=url_for('.download', version=version, file=role))
    return jsonify(version=version, materials=materials)


@studio_releases.get('/releases/<version>/download')
def download(version):
    row = access.catalog().get(version)
    if row is None:
        return _error('not_found', 404)
    if set(request.args) - {'file'} or len(request.args.getlist('file')) > 1:
        return _error('invalid_request', 400)
    role = request.args.get('file', 'kit')
    if role not in access.ROLES:
        return _error('not_found', 404)
    path, entry = access.verified_artifact(row, role)
    return send_file(path, as_attachment=True, download_name=entry['name'], conditional=True)
