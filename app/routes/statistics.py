"""Authenticated analytics and bounded first-party visitor presence."""
import csv
import hashlib
import hmac
import io
import os
from pathlib import Path
import secrets
import time
import click
from flask import Blueprint, abort, current_app, jsonify, render_template, request, Response, session
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from app.models import Station, AudiencePresence
from app.services.admin_auth import admin_required, current_admin
from app.services.statistics import dashboard
from app.services.statistics import geo, collect
from app.services.stations import public_station_for

statistics = Blueprint('statistics', __name__)


def can_view_statistics(user, station=None):
    return bool(user and user.active)


def context(slug):
    station = Station.query.filter_by(slug=slug).first_or_404() if slug else None
    if not can_view_statistics(current_admin(), station):
        abort(403)
    return station


@statistics.get('/admin/stats')
@statistics.get('/admin/stations/<slug>/stats')
@admin_required
def page(slug=None):
    station = context(slug)
    return render_template('admin/statistics.html', selected=station,
        stations=Station.query.order_by(Station.name).all(), page='stats')


@statistics.get('/admin/stats/data')
@statistics.get('/admin/stations/<slug>/stats/data')
@admin_required
def data(slug=None):
    station = context(slug)
    try:
        result = dashboard(station.id if station else 0, request.args)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    response = jsonify(result)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@statistics.get('/admin/stats/export.csv')
@statistics.get('/admin/stations/<slug>/stats/export.csv')
@admin_required
def export(slug=None):
    station = context(slug)
    try:
        result = dashboard(station.id if station else 0, request.args)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    output = io.StringIO()
    writer = csv.writer(output)
    def write(*values):
        writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
    write('Scope', station.name if station else 'All stations')
    write('Timezone', result['timezone'])
    write('Start (Unix UTC)', result['period']['start'], 'End (exclusive Unix UTC)', result['period']['end'])
    write('Observed coverage (%)', result['stats']['total']['coverage'])
    write('Resolution (seconds)', result['stats']['resolution_seconds'])
    write('Section', 'Timestamp / name', 'Average / count', 'Peak', 'Transfer bytes / dislikes')
    for point in result['stats']['timeline']:
        write('Audience', point['at'], point['average'], point['peak'], round(point['bytes']))
    for song in result['music']['songs']:
        write('Confirmed plays', song['title'] + ' — ' + song['artist'], song['plays'])
    for song in result['music']['liked']:
        write('Current preferences', song['title'] + ' — ' + song['artist'], song['up'], '', song['down'])
    for place in result['geography']['locations']:
        write('Approximate locations', ', '.join(filter(None, [place.get('city'), place.get('region'), place.get('country')])), place['count'])
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename="freo-statistics.csv"'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@statistics.route('/api/stations/<slug>/presence', methods=['GET', 'POST'])
def visitor_presence(slug):
    try:
        station = public_station_for(slug)
    except ValueError:
        station = None
    if not station or not station.enabled or station.deleted_at:
        abort(404)
    if current_admin():
        return jsonify(ignored=True)
    if request.method == 'GET':
        session.setdefault('stats_key', secrets.token_hex(32))
        session.setdefault('stats_csrf', secrets.token_urlsafe(32))
        response = jsonify(csrf=session['stats_csrf'])
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    if request.content_length and request.content_length > 512:
        abort(413)
    if not session.get('stats_csrf') or not hmac.compare_digest(request.headers.get('X-Presence-CSRF', ''), session['stats_csrf']):
        abort(400)
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    now = int(time.time())
    address = request.remote_addr or ''
    if address in current_app.config.get('DMCA_TRUSTED_PROXY_IPS', ()):
        address = request.headers.get('X-Real-IP', address)
    rate_key = hmac.new(current_app.secret_key.encode(), f'{now // 86400}:{address}'.encode(), hashlib.sha256).hexdigest()
    key = hmac.new(current_app.secret_key.encode(), session['stats_key'].encode(), hashlib.sha256).hexdigest()
    try:
        collect.lock(station.id)
        limit = db.session.get(AudiencePresence, (station.id, 'rate', rate_key))
        if limit and now - limit.first_seen < 60 and limit.geo.get('count', 0) >= 120:
            return jsonify(error='Too many presence updates'), 429
        if limit is None:
            limit = AudiencePresence(scope=station.id, source='rate', key=rate_key, first_seen=now, last_seen=now, geo={})
            db.session.add(limit)
        if now - limit.first_seen >= 60:
            limit.first_seen, limit.geo = now, {}
        limit.last_seen = now
        limit.geo = dict(count=limit.geo.get('count', 0) + 1)
        existing = db.session.get(AudiencePresence, (station.id, 'website', key))
        if not existing or now - existing.last_seen >= 20:
            collect.presence(station.id, 'website', key, existing.geo if existing else geo.lookup(address), now)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(error='Presence temporarily unavailable'), 503
    return Response(status=204)


@statistics.cli.group('stats')
def cli():
    """Collect local statistics independently of Central reporting."""


@cli.command('run')
@click.option('--once', is_flag=True)
def run(once):
    import fcntl
    from app.services.statistics.icecast import Icecast
    directory = Path(current_app.config['FREO_STATS_STATE_DIR'])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    credential = Path(os.environ.get('CREDENTIALS_DIRECTORY', str(directory))) / 'icecast.json'
    client = Icecast(credential)
    with (directory / 'worker.lock').open('w') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise click.ClickException('Statistics collector is already running') from None
        while True:
            start = time.monotonic()
            try:
                stations = Station.query.filter_by(deleted_at=None).all()
                observations = client.observe(stations)
                collect.tick(observations, int(time.time()))
            except Exception as error:
                db.session.rollback()
                current_app.logger.error('Statistics collection failed (%s)', type(error).__name__)
                if once:
                    raise click.ClickException('Collection failed; check the private service log') from None
            finally:
                db.session.remove()
            if once:
                break
            time.sleep(max(1, 15 - (time.monotonic() - start)))


@cli.command('inventory')
def inventory_command():
    from app.services.statistics.storage import inventory
    result = inventory(int(time.time()))
    click.echo(f"Stored media and images: {result['total']} bytes; missing files: {result['missing']}; inaccessible paths: {result['errors']}")


@cli.command('update-geoip')
def update_geoip():
    import gzip
    import tempfile
    from datetime import datetime, timezone
    from urllib.request import urlopen, Request
    import maxminddb
    target = Path(current_app.config['FREO_GEOIP_DATABASE'])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    url = f'https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz'
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        compressed = Path(directory) / 'database.gz'
        download = Request(url, headers={'User-Agent': 'Freo/1.0 (local geolocation update)', 'Referer': 'https://db-ip.com/'})
        with urlopen(download, timeout=60) as response, compressed.open('wb') as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 256 * 1024 * 1024:
                    raise click.ClickException('Geographic database download exceeded size limit')
                output.write(chunk)
        expanded = Path(directory) / 'City.mmdb'
        with gzip.open(compressed, 'rb') as source, expanded.open('wb') as output:
            count = 0
            while chunk := source.read(1024 * 1024):
                count += len(chunk)
                if count > 512 * 1024 * 1024:
                    raise click.ClickException('Geographic database exceeded size limit')
                output.write(chunk)
        with maxminddb.open_database(str(expanded)) as reader:
            if not reader.get('8.8.8.8'):
                raise click.ClickException('Geographic database validation failed')
        expanded.chmod(0o640)
        os.replace(expanded, target)
    click.echo(f'Updated local geographic database ({month}); attribution: https://db-ip.com')
