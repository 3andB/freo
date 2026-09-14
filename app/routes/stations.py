"""Public, read-only station metadata and observed status."""
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from flask import Blueprint, jsonify

from app.models import Station
from app.services.stations import get_station, public_station, validate_slug

stations_blueprint = Blueprint('stations', __name__)
_OPENER = build_opener(ProxyHandler({}))


def observed_status(station):
    slug = station.slug
    socket = Path('/run/freo/playout') / slug / 'control.sock'
    playout = 'running' if socket.is_socket() else 'stopped'
    mount = 'offline'
    stream = 'offline'
    try:
        with _OPENER.open('http://127.0.0.1:8001/status-json.xsl', timeout=2) as response:
            sources = json.load(response)['icestats'].get('source', [])
        if isinstance(sources, dict):
            sources = [sources]
        if any(item.get('listenurl', '').endswith('/' + slug) for item in sources):
            mount = 'online'
            with _OPENER.open('http://127.0.0.1:8001/' + slug, timeout=3) as response:
                if response.status == 200 and response.headers.get_content_type() == 'audio/mpeg' and response.read(512):
                    stream = 'online'
    except (OSError, ValueError, KeyError):
        pass
    return {'slug': slug, 'desired_state': station.desired_state, 'playout': playout, 'icecast_mount': mount, 'stream': stream}


@stations_blueprint.get('/api/stations')
def list_stations():
    stations = Station.query.order_by(Station.slug).all()
    return jsonify(stations=[public_station(s) for s in stations])


@stations_blueprint.get('/api/stations/<slug>')
def show_station(slug):
    try:
        station = get_station(slug)
    except ValueError:
        station = None
    if station is None:
        return jsonify(status='not_found'), 404
    return jsonify(public_station(station))


@stations_blueprint.get('/api/stations/<slug>/status')
def station_status(slug):
    try:
        station = get_station(slug)
    except ValueError:
        station = None
    if station is None:
        return jsonify(status='not_found'), 404
    return jsonify(observed_status(station))
