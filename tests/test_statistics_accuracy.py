"""Reporting edge cases and parity across summaries, series and CSV."""
import csv
import io
import time
from datetime import datetime, timedelta, timezone
import pytest
from app.extensions import db
from app.models import StatsState, StatsBucket, SelectionDecision, ListenerVote, ListenerFeedbackEvent, Track, BroadcastIncident
from app.services.statistics import aggregate, ranking, collect
from tests.test_web import app, admin_client
from tests.test_statistics import observation


def test_saved_snapshot_ledger_uses_the_report_cutoff_for_plays(app, tmp_path):
    from tests.test_statistics_soak import Ledger
    now = int(time.time())
    ledger = Ledger(tmp_path)
    observations = {1: dict(online=True, listeners=0, clients=[]),
                    2: dict(online=False, listeners=0, clients=[])}
    with app.app_context():
        # A backup can contain a play recorded after its latest listener sample.
        SelectionDecision.query.update({'started_at': datetime.fromtimestamp(now+5, timezone.utc)})
        db.session.commit()
        collect.tick(observations, now)
        ledger.observe(observations, now)
        assert SelectionDecision.query.filter_by(status='started').count() == 1
        assert ranking(1, now-86400, now+1)['plays'] == 0
        ledger.verify(now)
        assert ranking(1, now-86400, now+11)['plays'] == 1
        ledger.verify(now+10)


def test_incident_total_is_not_the_display_limit(app):
    now = int(time.time())
    with app.app_context():
        db.session.add_all([BroadcastIncident(scope=1, kind='observation_gap', started_at=now-300+i,
                            ended_at=now-299+i, detail='Fixture gap') for i in range(125)])
        db.session.add(BroadcastIncident(scope=2, kind='observation_gap', started_at=now-10, detail='Other station'))
        db.session.commit()
    client = admin_client(app)
    result = client.get('/admin/stations/test-station/stats/data').json
    assert result['incident_count'] == 125 and len(result['incidents']) == 100
    assert client.get('/admin/stats/data').json['incident_count'] == 126
    exported = client.get('/admin/stations/test-station/stats/export.csv').text
    assert 'Reliability summary,recorded_incidents,125' in exported
    assert 'Reliability summary,incident_rows_exported,100' in exported


def test_transfer_series_distinguishes_missing_observations_from_known_zero(app):
    with app.app_context():
        db.session.add(StatsState(scope=1, data={'at': 180}))
        collect.accumulate(1, 60, 120, listeners=0, online=False, transfer=0)
        collect.accumulate(1, 120, 180, listeners=3, online=True, transfer=17)
        db.session.commit()
        points = aggregate(1, 0, 180, now=180)['timeline']
        assert [p['transfer_bytes'] for p in points] == [None, 0, 17]
        assert [p['average'] for p in points] == [None, 0, 3]
        assert sum(p['bytes'] for p in points) == 17


def test_stale_peak_outside_report_is_not_included(app):
    with app.app_context():
        db.session.add(StatsState(scope=1, data={'at': 61}))
        db.session.add(StatsBucket(scope=1, resolution='minute', at=60, peak=8))
        db.session.commit()
        assert aggregate(1, 62, 100, now=100)['total']['peak'] == 0
        assert aggregate(1, 61, 100, now=100)['total']['peak'] == 8


def test_feedback_and_plays_keep_distinct_time_and_station_semantics(app):
    now = int(time.time())
    with app.app_context():
        track = Track.query.one()
        SelectionDecision.query.update({'started_at': datetime.fromtimestamp(now-10, timezone.utc)})
        for n, (station, value, excluded) in enumerate([(1, 1, False), (1, -1, False), (1, 1, True), (2, 1, False)]):
            db.session.add(ListenerVote(station_id=station, track_id=track.id, listener_key=str(n), value=value,
                                        decision_id=1, excluded=excluded, updated_at=datetime.fromtimestamp(now-86400, timezone.utc)))
            db.session.add(ListenerFeedbackEvent(station_id=station, listener_key=str(n), track_id=track.id,
                                                 action='vote', value=value, created_at=datetime.fromtimestamp(now-10, timezone.utc)))
        db.session.commit()
        current = ranking(1, now-60, now)
        assert current['plays'] == 1 and current['unique_songs'] == 1
        assert current['feedback'] == dict(up=1, down=1, total=2, approval=50, activity=3, changes=0, removals=0)
        assert ranking(2, now-60, now)['feedback']['approval'] == 100
        past = ranking(1, now-3600, now-1800)
        assert past['plays'] == 0 and past['feedback']['activity'] == 0
        assert past['feedback']['approval'] == 50  # Current accepted votes, intentionally not historical.


def test_csv_summary_matches_dashboard_and_keeps_unknown_transfer_blank(app, monkeypatch):
    now = int(time.time()) // 60 * 60 + 30
    monkeypatch.setattr('app.services.statistics.time.time', lambda: now)
    with app.app_context():
        collect.tick({1: observation(2, 100), 2: observation(0, 100)}, now-30)
        collect.tick({1: observation(4, 200), 2: observation(0, 200)}, now-15)
    client = admin_client(app)
    result = client.get('/admin/stations/test-station/stats/data?range=live').json
    exported = client.get('/admin/stations/test-station/stats/export.csv?range=live')
    rows = list(csv.reader(io.StringIO(exported.text)))
    summaries = {r[1]: r[2] for r in rows if r and r[0] == 'Audience summary'}
    for key in ('average', 'peak', 'listener_hours', 'coverage', 'bytes_sent'):
        assert float(summaries[key]) == pytest.approx(result['stats']['total'][key])
    assert any(r[0] == 'Audience' and r[2] == '' and r[4] == '' for r in rows if r)
    assert any(r[:3] == ['Geography metadata', 'source', 'stream'] for r in rows)
