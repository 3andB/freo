"""Operations scope, cached observations, and cross-station moderation boundaries."""
from datetime import datetime, timezone
import time

from app.extensions import db
from app.models import (BroadcastIncident, CentralInstallation, CentralStationState, ListenerVote, LiveQueueSnapshot,
                        SelectionDecision, Station, StatsState, StorageSnapshot, Track)
from app.services.operations import snapshot
from tests.test_web import app, admin_client


def navigation(response):
    return response.get_data(as_text=True).split('<nav class="admin-nav"', 1)[1].split('</nav>', 1)[0]


def test_local_license_ignores_legacy_remote_two_station_limit(app):
    with app.app_context():
        from app.services.operations import connection
        db.session.add(CentralInstallation(id=1, license_cache={
            'entitlement': {'plan': 'free', 'status': 'expired', 'channel_limit': 2}}))
        db.session.commit()
        result = connection(Station.query.all(), int(time.time()))
        assert result['channel_limit'] == 3
        assert result['plan'] == 'Free · three stations per owner'
        assert result['entitlement_status'] == 'Active · registration optional'


def test_operations_navigation_never_selects_a_station(app, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('Overview must read local observations')
    monkeypatch.setattr('app.routes.stations._OPENER.open', no_network)
    monkeypatch.setattr('app.services.central_api.client.Client.request', no_network)
    client = admin_client(app)
    for path in ('/admin', '/admin?station=test-station', '/admin/stats', '/admin/player-settings',
                 '/admin/listener-feedback', '/admin/website', '/admin/dmca', '/admin/installation'):
        response = client.get(path)
        assert response.status_code == 200, path
        nav = navigation(response)
        assert 'data-context="operations"' in nav
        assert 'Operations Statistics' in nav and 'Listener Feedback' in nav
        assert 'DJ Booth' not in nav and 'Station Control' not in nav
        assert '>View<' not in nav and '>Switch<' in nav
        assert 'value="test-station"' in nav
    assert client.get('/admin/stations').headers['Location'] == '/admin#stations'
    assert 'Second Station' in client.get('/admin').text
    assert 'Verified Test Track' in client.get('/admin').text


def test_switch_and_direct_urls_restore_station_context(app):
    client = admin_client(app)
    response = client.get('/admin/switch-station?station=second-station')
    assert response.status_code == 302
    assert response.headers['Location'] == '/admin/stations/second-station/schedule-studio/control'
    response = client.get(response.headers['Location'])
    assert response.status_code == 200
    nav = navigation(response)
    assert 'data-context="station"' in nav and 'Second Station' in nav
    assert 'DJ Booth' in nav and 'Station Control' in nav
    assert '/admin/stations/test-station/' not in nav
    assert 'Admin Audit' not in nav and 'Operations Statistics' not in nav
    assert 'href="/admin"' in nav
    assert client.get('/admin/switch-station?station=missing').status_code == 404
    assert client.get('/admin/switch-station').status_code == 404
    with app.app_context():
        Station.query.filter_by(slug='second-station').one().lifecycle_state = 'pending_delete'
        db.session.commit()
    assert client.get('/admin/switch-station?station=second-station').status_code == 404


def test_snapshot_freshness_connection_sync_and_safe_fields(app):
    now = int(time.time())
    with app.app_context():
        from app.services.central_api import metadata, digest
        stations = Station.query.order_by(Station.id).all()
        decision = SelectionDecision.query.first()
        db.session.add_all([
            BroadcastIncident(scope=stations[0].id, kind='silence', started_at=now, detail='Program audio is silent'),
            StatsState(scope=0, data={'at': now, 'listeners': 17}),
            StatsState(scope=stations[0].id, data={'at': now, 'listeners': 17, 'online': True}),
            LiveQueueSnapshot(station_id=stations[0].id, current_decision_id=decision.id,
                              observed_at=datetime.fromtimestamp(now, timezone.utc)),
            CentralInstallation(id=1, installation_id='identity', registration_state='enrolled',
                                state={'last_heartbeat': {'server_time': datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
                                       'activation': {'code': 'DO-NOT-EXPOSE'}}),
            CentralStationState(station_id=stations[0].id, synced_digest=digest(metadata(stations[0]))),
            StorageSnapshot(scope=0, at=now, data={'total': 12345}),
        ])
        db.session.commit()
        data = snapshot(stations, now)
        assert data['summary']['listeners'] == 17
        assert data['summary']['storage'] == 12345
        assert 'Program audio is silent' in data['stations']['test-station']['issues']
        assert data['stations']['test-station']['status'] == 'On air'
        assert data['stations']['test-station']['playback_label'] == 'On air now'
        assert data['connection']['connected']
        assert data['connection']['synced'] == '1 / 2 stations up to date'
        stations[0].name = 'Changed metadata'
        assert snapshot(stations, now)['connection']['synced'] == '0 / 2 stations up to date'
        data = snapshot(stations, now + 4000)
        assert data['summary']['listeners'] is None
        assert data['stations']['test-station']['status'] == 'Unknown'
        assert data['stations']['test-station']['playback_label'] == 'Last confirmed start'
        assert data['connection']['status'] == 'Connection stale'
    response = admin_client(app).get('/admin/api/operations')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
    for secret in ('DO-NOT-EXPOSE', 'internal.mp3', 'password_hash', 'access_token'):
        assert secret not in response.text


def test_snapshot_does_not_count_station_peaks_or_duplicate_storage(app):
    from app.services.statistics import collect
    now = int(time.time())
    with app.app_context():
        stations = Station.query.order_by(Station.id).all()
        for offset, counts in [(-30, (9, 1)), (-15, (1, 9)), (0, (3, 3))]:
            collect.tick({s.id: dict(online=True, listeners=n, clients=[]) for s, n in zip(stations, counts)}, now + offset)
        data = snapshot(stations, now)
        assert data['summary']['peak'] == 10  # Not 9 + 9 from peaks at different times.
        assert data['summary']['listeners'] == 6
        assert data['summary']['coverage'] > 0


def test_feedback_operations_filter_and_scoped_moderation(app):
    with app.app_context():
        stations = Station.query.order_by(Station.id).all()
        track = Track.query.first()
        for s, comment in zip(stations, ('First station comment', 'Second station comment')):
            db.session.add(ListenerVote(station_id=s.id, track_id=track.id, listener_key='visitor',
                                       decision_id=1, value=1, comment=comment))
        db.session.commit()
        second_id = ListenerVote.query.filter_by(station_id=stations[1].id).one().id
    client = admin_client(app)
    assert 'First station comment' in client.get('/admin/listener-feedback').text
    assert 'Second station comment' in client.get('/admin/listener-feedback').text
    response = client.get('/admin/listener-feedback?station=second-station')
    assert 'First station comment' not in response.text
    assert 'Second station comment' in response.text
    assert 'data-context="operations"' in navigation(response)
    form = dict(id=second_id, revision=1, action='reviewed', csrf='test-admin-csrf-token', return_to='operations')
    assert client.post('/admin/stations/test-station/listener-feedback', data=form).status_code == 404
    response = client.post('/admin/stations/second-station/listener-feedback', data=form)
    assert response.headers['Location'] == '/admin/listener-feedback'
    assert 'Second station comment' not in client.get('/admin/listener-feedback?review=new').text
    assert client.post('/admin/stations/second-station/listener-feedback', data={**form, 'csrf': ''}).status_code == 400
    response = client.post('/admin/stations/second-station/listener-feedback', data={**form, 'action': 'spam'}, follow_redirects=True)
    assert 'Feedback changed' in response.text
    with app.app_context():
        assert db.session.get(ListenerVote, second_id).review_state == 'reviewed'


def test_empty_installation_and_operations_auth(app):
    client = app.test_client()
    for path in ('/admin/api/operations', '/admin/player-settings', '/admin/listener-feedback', '/admin/switch-station'):
        assert client.get(path).headers['Location'].endswith('/admin/login')
    with app.app_context():
        Station.query.update({'deleted_at': datetime.now(timezone.utc)})
        db.session.commit()
    client = admin_client(app)
    response = client.get('/admin')
    assert response.status_code == 200
    assert 'No managed stations yet' in response.text
    assert 'Connection to mother ship established' not in response.text
    assert 'Add station' in response.text
    assert client.get('/admin/player-settings').status_code == 200
    assert client.get('/admin/listener-feedback').status_code == 200
