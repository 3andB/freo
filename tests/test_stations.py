import pytest

from app import create_app
from app.extensions import db
from app.services.stations import create_station, validate_slug, set_enabled
from app.services.station_runtime import unit_name, service_action, render_liquidsoap
from app.routes import stations as station_routes


@pytest.fixture
def station_app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_valid_create_and_read_only_api(station_app, monkeypatch):
    with station_app.app_context():
        station = create_station('Demo', 'freo-demo')
        assert station.stream.mount == '/freo-demo'
        assert station.stream.public_path == '/stream/freo-demo'
        with pytest.raises(ValueError, match='already exists'):
            create_station('Duplicate', 'freo-demo')
    monkeypatch.setattr(station_routes, 'observed_status', lambda s: {'slug': s.slug, 'desired_state': 'stopped', 'playout': 'stopped', 'icecast_mount': 'offline', 'stream': 'offline'})
    client = station_app.test_client()
    assert client.get('/api/stations').json['stations'][0]['slug'] == 'freo-demo'
    assert client.get('/api/stations/freo-demo').json['stream_path'] == '/stream/freo-demo'
    assert client.get('/api/stations/freo-demo/status').json['playout'] == 'stopped'
    assert client.post('/api/stations', json={'slug':'evil'}).status_code == 405
    assert client.patch('/api/stations/freo-demo', json={'enabled':False}).status_code == 405
    assert client.post('/api/stations/freo-demo/start').status_code == 404


@pytest.mark.parametrize('slug', ['../../etc/passwd','../foo','rock/101','rock 101','rock;shutdown','$(whoami)','--test','admin','%2f','rоck','freo-test','a-','-a',''])
def test_malicious_slugs_rejected(slug):
    with pytest.raises(ValueError):
        validate_slug(slug)
    with pytest.raises(ValueError):
        unit_name(slug)


def test_known_unit_name_only():
    assert unit_name('rock101') == 'freo-playout@rock101.service'
    for slug in ('nginx.service','ssh','postgresql','freo.service'):
        if slug.endswith('.service'):
            with pytest.raises(ValueError):
                unit_name(slug)
    with pytest.raises(ValueError):
        service_action('nginx.service', 'start')
    with pytest.raises(ValueError):
        service_action('freo-demo', 'reload')


def test_status_response_has_no_secret(station_app, monkeypatch):
    with station_app.app_context():
        create_station('Demo', 'demo')
    monkeypatch.setattr(station_routes, 'observed_status', lambda s: {'slug':s.slug,'desired_state':'stopped','playout':'stopped','icecast_mount':'offline','stream':'offline'})
    body = station_app.test_client().get('/api/stations/demo/status').get_data(as_text=True)
    assert 'password' not in body and 'secret' not in body and '/etc/freo' not in body


def test_disabled_station_is_stopped(station_app):
    with station_app.app_context():
        station = create_station('Demo', 'disabled-demo')
        station.desired_state = 'running'
        db.session.commit()
        set_enabled(station, False)
        assert station.enabled is False
        assert station.desired_state == 'stopped'


def test_station_text_is_quoted_in_liquidsoap(station_app):
    with station_app.app_context():
        station = create_station('Bad"); system("whoami")', 'quoted-demo')
        rendered = render_liquidsoap(station, 'a' * 64)
        assert 'Bad\\"); system(\\"whoami\\")' in rendered
        assert 'password="' + ('a' * 64) + '"' in rendered
        assert 'mode = ref("AUTO")' in rendered
        from app.models import AutomationState
        station.automation = AutomationState(operator_mode='DJ_BOOTH')
        assert 'mode = ref("DJ_BOOTH")' in render_liquidsoap(station, 'a' * 64)
