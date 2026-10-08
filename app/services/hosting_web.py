"""Hosted-only UI and transaction guards; absent from self-hosted responses."""
from contextlib import ExitStack
from flask import jsonify, render_template, request
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from freo_ops import hosting, hosting_storage


def transaction_guards(session, context, instances):
    policy = hosting.read()
    if not policy['hosted']:
        return
    from app.models import Station, StreamMount
    from app.services.stations import allocation_lock, active_stations
    additions = sum(isinstance(row, Station) for row in session.new)
    if additions:
        allocation_lock()
        hosting.check_stations(active_stations().count() + additions)
    growth = 0
    for row in session.new | session.dirty:
        if isinstance(row, StreamMount):
            hosting.check_bitrate(row.bitrate or 192)
            if row.pending_audio:
                hosting.check_bitrate(row.pending_audio.get('bitrate', 192))
        state = inspect(row)
        for column in state.mapper.columns:
            from sqlalchemy import LargeBinary
            if isinstance(column.type, LargeBinary):
                history = state.attrs[column.key].history
                if history.has_changes() and history.added and history.added[0]:
                    growth += len(history.added[0])
    if growth:
        stack = session.info.setdefault('hosting_reservations', ExitStack())
        stack.enter_context(hosting_storage.reserve(growth))


def end_transaction(session):
    stack = session.info.pop('hosting_reservations', None)
    if stack:
        stack.close()


def summary():
    policy = hosting.read()
    if not policy['hosted']:
        return None
    from app.services.stations import active_stations
    result = dict(policy, stations_used=active_stations().count())
    try:
        result['storage'] = hosting_storage.usage()
    except hosting.HostingError:
        result['storage'] = None
    try:
        import json
        from urllib.request import build_opener, ProxyHandler
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:8001/status-json.xsl', timeout=1) as response:
            data = json.loads(response.read(1_048_576))['icestats']
        sources = data.get('source', [])
        if isinstance(sources, dict):
            sources = [sources]
        result['listeners_used'] = sum(int(s.get('listeners', 0)) for s in sources)
    except Exception:
        result['listeners_used'] = 0 if policy['status'] in ('suspended', 'maintenance') else None
    return result


def install(app):
    if not event.contains(Session, 'before_flush', transaction_guards):
        event.listen(Session, 'before_flush', transaction_guards)
        event.listen(Session, 'after_commit', end_transaction)
        event.listen(Session, 'after_rollback', end_transaction)
    @app.errorhandler(hosting.HostingError)
    def hosting_error(error):
        return jsonify(error.response()), 409 if error.code.endswith('_exceeded') else 503
    @app.before_request
    def guard():
        if request.path.startswith('/static/') or request.path in ('/health', '/ready', '/admin/login', '/admin/logout', '/hosting/status'):
            return None
        try:
            policy = hosting.require_service()
            if policy['hosted'] and request.mimetype == 'multipart/form-data':
                from flask import g
                size = request.content_length
                if size is None:
                    raise hosting.HostingError('invalid_arguments', 'Media uploads require Content-Length.')
                reservation = hosting_storage.reserve(size)
                reservation.__enter__()
                g.hosting_upload_reservation = reservation
        except hosting.HostingError as error:
            if request.path.startswith('/api/') or '/api/' in request.path:
                return jsonify(error.response()), 503
            return render_template('hosting_status.html', state=hosting.read() if error.code != 'invalid_configuration' else {'status':'maintenance'}), 503
    @app.teardown_request
    def release_upload(error):
        from flask import g
        reservation = g.pop('hosting_upload_reservation', None)
        if reservation:
            reservation.__exit__(None, None, None)
    @app.get('/hosting/status')
    def status():
        # No commercial endpoint exposed on self-hosted instances.
        from flask import abort
        policy = hosting.read()
        if not policy['hosted']:
            abort(404)
        return render_template('hosting_status.html', state=policy)
    @app.context_processor
    def template_policy():
        return dict(hosting_summary=summary() if request.path.startswith('/admin') and request.path != '/admin/login' else None)
