from app import create_app
from app.routes import radio_health


def test_radio_health_reports_real_observations(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    client = create_app('testing').test_client()
    monkeypatch.setattr(radio_health, '_icecast_stats', lambda: {'server_id': 'Icecast'})
    monkeypatch.setattr(radio_health, '_stream_audio_available', lambda: True)
    monkeypatch.setattr(radio_health, '_test_source_present', lambda: True)
    monkeypatch.setattr(radio_health, '_socket_ready', lambda: True)
    for route in ('/health/icecast', '/health/playout', '/health/stream'):
        response = client.get(route)
        assert response.status_code == 200
        assert response.json == {'status': 'ok'}


def test_radio_health_failure_hides_details(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    client = create_app('testing').test_client()
    def fail():
        raise OSError('private backend detail')
    monkeypatch.setattr(radio_health, '_icecast_stats', fail)
    monkeypatch.setattr(radio_health, '_stream_audio_available', fail)
    for route in ('/health/icecast', '/health/stream'):
        response = client.get(route)
        assert response.status_code == 503
        assert response.json == {'status': 'unavailable'}
        assert 'private backend detail' not in response.get_data(as_text=True)
