"""Observed connection accounting, privacy, station boundaries and migration safety."""
import json
from datetime import datetime, timezone
import pytest
from app.extensions import db
from app.models import AudiencePresence, SessionBucket, StatsState, Station, StatsBucket, Track
from app.services.statistics import collect, dashboard, sessions
from tests.test_web import app, admin_client
from tests.test_phase3_dj import dj_client


def obs(ids=(), agent='Mozilla/5.0 (iPhone) Version/18.0 Mobile/15 Safari/604.1', epoch='server', source='source'):
    return dict(online=True, listeners=len(ids) if ids is not None else None,
                epoch=epoch, source_epoch=source,
                clients=None if ids is None else [dict(id=str(i), agent=agent, ip='192.0.2.1') for i in ids])


def tick(at, ids=(), **kwargs):
    collect.tick({1: obs(ids, **kwargs), 2: dict(online=False, listeners=0, clients=[])}, at)


def report(start=3600, end=7200, now=7200, scope=1):
    return sessions.report(scope, start, end, now)


@pytest.mark.parametrize('agent,device,player', [
    ('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36', 'desktop', 'Chrome'),
    ('Mozilla/5.0 (Macintosh) Version/18.0 Safari/605.1', 'desktop', 'Safari'),
    ('Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0', 'desktop', 'Firefox'),
    ('Mozilla/5.0 (iPhone) Version/18.0 Mobile Safari/605.1', 'mobile', 'Safari'),
    ('Mozilla/5.0 (iPad) Version/18.0 Mobile Safari/605.1', 'tablet', 'Safari'),
    ('Mozilla/5.0 (Android 14) Chrome/130.0 Mobile Safari/537.36', 'mobile', 'Chrome'),
    ('Mozilla/5.0 (Android 14) Chrome/130.0 Safari/537.36', 'tablet', 'Chrome'),
    ('Mozilla/5.0 (Android TV) Chrome/130.0', 'other/unknown', 'Chrome'),
    ('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Edg/130.0', 'desktop', 'Edge'),
    ('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 OPR/112.0', 'desktop', 'Opera'),
    ('VLC/3.0.20 LibVLC/3.0.20', 'other/unknown', 'VLC'),
    ('foobar2000/2.0', 'other/unknown', 'foobar2000'),
    ('Dalvik/2.1 (Android 14)', 'other/unknown', 'Other/unknown'),
    ('Mozilla/5.0 (Googlebot)', 'other/unknown', 'Other/unknown'),
    ('<script>window.alert(1)</script>', 'other/unknown', 'Other/unknown'),
    (None, 'other/unknown', 'Other/unknown'),
    (123, 'other/unknown', 'Other/unknown'),
])
def test_conservative_classification(agent, device, player):
    assert sessions.classify(agent) == (device, player)


def test_completed_active_duplicate_ticks_and_privacy(app):
    with app.app_context():
        tick(3600, ['one', 'two'])
        tick(3615, ['one', 'two'])
        tick(3615, [])  # Retry cannot double-count or finalize.
        tick(3630, ['two'])
        data = report(end=3631, now=3631)
        s = data['sessions']
        assert (s['starts'], s['completed'], s['active'], s['average_seconds']) == (2, 1, 1, 15)
        assert s['bands'][0]['count'] == 1
        assert next(g for g in data['devices']['groups'] if g['name'] == 'mobile')['current'] == 1
        tick(3645, [])
        tick(3660, [])
        s = report()['sessions']
        assert (s['starts'], s['completed'], s['average_seconds']) == (2, 2, 22.5)
        payload = json.dumps(dashboard(1, {'range': 'live'}, now=3661))
        assert all(private not in payload for private in ('192.0.2.1', 'Mozilla', 'iPhone'))
        for row in AudiencePresence.query.filter_by(source='stream'):
            assert row.key not in payload
            assert '192.0.2.1' not in json.dumps(row.listening)


@pytest.mark.parametrize('threshold', sessions.THRESHOLDS)
def test_exact_duration_thresholds(app, threshold):
    with app.app_context():
        for at in range(3600, 3600 + threshold + 1, 30):
            tick(at, ['one'])
        tick(3630 + threshold, [])
        s = report(end=3660 + threshold, now=3660 + threshold)['sessions']
        assert s['average_seconds'] == threshold
        assert s['bands'][sessions.THRESHOLDS.index(threshold) + 1]['count'] == 1
        assert [r['share'] for r in s['retention']] == [100 if t <= threshold else 0 for t in sessions.THRESHOLDS]


@pytest.mark.parametrize('reason', ['gap', 'server', 'source', 'failed_list'])
def test_interruption_never_becomes_completion(app, reason):
    with app.app_context():
        tick(3600, ['one'])
        tick(3615, ['one'])
        if reason == 'gap':
            tick(3690, ['one'])
        elif reason == 'server':
            tick(3630, ['one'], epoch='new-server')
        elif reason == 'source':
            tick(3630, ['one'], source='new-source')
        else:
            tick(3630, None)
            assert report(end=3631, now=3631)['sessions']['active'] is None
            tick(3661, None)
            tick(3676, ['one'])
        s = report()['sessions']
        assert (s['starts'], s['completed'], s['interrupted'], s['average_seconds']) == (2, 0, 1, None)
        assert all(r['share'] is None for r in s['retention'])


def test_short_failed_list_gap_reconnect_and_offline(app):
    with app.app_context():
        tick(3600, ['one'])
        tick(3615, None)
        tick(3630, ['one'])
        collect.tick({1: dict(online=False, listeners=0, epoch='server', clients=[]), 2: obs()}, 3645)
        assert report()['sessions']['average_seconds'] == 30
        tick(3660, ['one'])
        assert report()['sessions']['starts'] == 2


def test_offline_server_restart_after_failed_poll_is_interrupted(app):
    with app.app_context():
        tick(3600, ['one'])
        tick(3615, ['one'])
        collect.tick({}, 3630)  # Entire Icecast observation is unavailable, losing its epoch checkpoint.
        collect.tick({1: dict(online=False, listeners=0, epoch='new-server', clients=[])}, 3645)
        s = report()['sessions']
        assert s['interrupted'] == 1 and s['completed'] == 0


def test_hour_boundaries_coverage_and_weighted_averages(app):
    with app.app_context():
        tick(3585, ['one'])
        tick(3615, ['one'])
        tick(3630, [])
        tick(7185, ['two'])
        tick(7200, [])
        first = report(start=3500, end=3601, now=8000)['sessions']
        assert (first['start'], first['end'], first['resolution_seconds']) == (0, 7200, 3600)
        assert first['starts'] == 2 and first['completed'] == 2
        assert first['average_seconds'] == 15
        assert sum(p['completed'] or 0 for p in first['timeline']) == 2
        assert first['coverage'] == pytest.approx(60 / 7200 * 100)
        assert SessionBucket.query.filter_by(scope=1, at=0).one().data['covered_seconds'] == 15
        assert SessionBucket.query.filter_by(scope=1, at=3600).one().data['covered_seconds'] == 45


def test_empty_history_existing_presence_and_retention_cleanup(app):
    with app.app_context():
        assert report()['sessions']['starts'] is None
        assert report()['sessions']['active'] is None
        db.session.add(AudiencePresence(scope=1, source='stream', key='legacy', first_seen=1, last_seen=3590, geo={}))
        db.session.commit()
        tick(3600, ['one'])
        tick(3615, [])
        assert report()['sessions']['average_seconds'] == 0
        assert report(start=-7200, end=-3600)['sessions']['starts'] is None
        tick(90000, [])
        tick(93601, [])
        assert AudiencePresence.query.count() == 0
        assert report()['sessions']['completed'] == 1
        tick(5 * 366 * 86400 + 100000, [])
        assert SessionBucket.query.filter(SessionBucket.at < 100000).count() == 0


def test_transaction_retry_preserves_single_accounting(app, monkeypatch):
    with app.app_context():
        tick(3600, ['one'])
        commit = db.session.commit
        monkeypatch.setattr(db.session, 'commit', lambda: (_ for _ in ()).throw(RuntimeError('rollback test')))
        with pytest.raises(RuntimeError):
            tick(3615, [])
        db.session.rollback()
        monkeypatch.setattr(db.session, 'commit', commit)
        tick(3615, [])
        assert report()['sessions']['completed'] == 1
        assert report()['sessions']['starts'] == 1


def test_archival_and_missing_station_do_not_fabricate_current_counts(app):
    with app.app_context():
        collect.tick({1: obs(['one']), 2: obs(['two'])}, 3600)
        collect.tick({1: obs(['one']), 2: obs(['two'])}, 3615)
        db.session.get(Station, 2).deleted_at = datetime.fromtimestamp(3615, timezone.utc)
        db.session.commit()
        tick(3630, ['one'])
        data = report(end=3631, now=3631, scope=0)['sessions']
        assert data['active'] == 1
        assert data['coverage'] == pytest.approx(45 / 46 * 100)
        assert report(end=3631, now=3631, scope=2)['sessions']['active'] is None
        tick(3676, [])
        assert report(scope=2)['sessions']['interrupted'] == 1
        db.session.get(Station, 2).deleted_at = None
        db.session.delete(db.session.get(StatsState, 2))
        db.session.commit()
        assert report(end=3677, now=3677, scope=0)['sessions']['active'] is None


def test_summary_uses_completed_counts_as_weights(app):
    with app.app_context():
        for at, count, seconds in [(3600, 1, 600), (7200, 3, 60)]:
            values = sessions.empty()
            values.update(starts=count, completed=count, duration_seconds=seconds, covered_seconds=60)
            db.session.add(SessionBucket(scope=1, at=at, data=values))
        db.session.commit()
        s = report(start=3600, end=10800, now=10800)['sessions']
        assert s['average_seconds'] == 165  # (600 + 60) / 4, not mean(600, 20).
        assert [p['average_seconds'] for p in s['timeline']] == [600, 20]


def test_routes_station_isolation_export_comparison_and_permissions(app, dj_client):
    import time
    now = int(time.time())
    with app.app_context():
        tick(now - 30, ['one'])
        tick(now - 15, ['one'])
        tick(now, [])
    client = admin_client(app)
    for suffix in ('', '/data', '/export.csv'):
        for prefix in ('/admin/stats', '/admin/stations/test-station/stats', '/admin/stations/second-station/stats'):
            assert dj_client.get(prefix + suffix).status_code == 403
            assert app.test_client().get(prefix + suffix).status_code == 302
    result = client.get('/admin/stations/test-station/stats/data?compare=1').json
    assert result['sessions']['completed'] == 1 and result['sessions']['previous'] is not None
    assert {r['id'] for r in result['channels']} == {1}
    other = client.get('/admin/stations/second-station/stats/data').json
    assert other['sessions']['completed'] == 0
    assert {r['id'] for r in other['channels']} == {2}
    exported = client.get('/admin/stations/test-station/stats/export.csv')
    assert exported.headers['Cache-Control'] == 'private, no-store'
    assert b'Sessions,average_seconds,15.0' in exported.data
    assert b'Devices,mobile,1,100.0,0' in exported.data
    assert b'Duration retention' in exported.data and b'Session trend' in exported.data
    with app.app_context():
        for zone in ('UTC', 'Australia/Eucla', 'America/New_York'):
            data = dashboard(1, {'range': 'yesterday', 'timezone': zone}, now=now)
            assert data['sessions']['start'] <= data['period']['start']
            assert data['sessions']['end'] >= data['period']['end']


def test_migration_round_trip_preserves_legacy_data(app):
    with app.app_context():
        db.session.add(AudiencePresence(scope=1, source='stream', key='legacy', first_seen=100, last_seen=200, geo={'place': 'unknown'}))
        db.session.add(StatsState(scope=1, data=dict(at=200, sessions_since=100, session_clients_at=200, session_clients_valid=True)))
        db.session.add(StatsBucket(scope=1, resolution='hour', at=0, listener_seconds=1234))
        db.session.commit()
    runner = app.test_cli_runner()
    # This create_all fixture already includes later, unrelated V1 tables.
    # Round-trip only the session migration; the full chain has its own harness.
    for args in (['db', 'stamp', 'f406a1b2c3d4'], ['db', 'downgrade', 'f316a1b2c3d4'],
                 ['db', 'upgrade', 'f406a1b2c3d4'], ['db', 'downgrade', 'f316a1b2c3d4'],
                 ['db', 'upgrade', 'f406a1b2c3d4']):
        result = runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        assert Track.query.count() == 1
        row = AudiencePresence.query.one()
        assert (row.first_seen, row.last_seen, row.listening) == (100, 200, None)
        assert SessionBucket.query.count() == 0
        assert db.session.get(StatsState, 1).data == {'at': 200}
        assert StatsBucket.query.one().listener_seconds == 1234


def test_malformed_client_list_is_not_evidence_of_departure():
    from app.services.statistics.icecast import Icecast
    from types import SimpleNamespace
    from xml.etree.ElementTree import fromstring
    client = Icecast.__new__(Icecast)
    for body in ('<error/>', '<icestats/>', '<icestats><source mount="/other"/></icestats>',
                 '<icestats><source mount="/one"><listener><ip>192.0.2.1</ip></listener></source></icestats>'):
        client.read = lambda path: fromstring('<icestats><source mount="/one"><listeners>1</listeners></source></icestats>' if path == '/admin/stats' else body)
        assert client.observe([SimpleNamespace(id=1, slug='one')])[1]['clients'] is None
