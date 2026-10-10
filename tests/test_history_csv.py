"""History downloads preserve station scope, confirmed starts, and spreadsheet safety."""
import csv
import io
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models import AdminUser, Station, SelectionDecision, Track, TimedEventOccurrence
from tests.test_web import app, admin_client

BASE = '/admin/stations/test-station/history.csv'


def rows(response):
    return list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))


def test_history_exports_all_confirmed_rows_and_empty_station(app):
    client = admin_client(app)
    with app.app_context():
        original = SelectionDecision.query.one()
        stamp = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        original.started_at = stamp
        station = db.session.get(Station, original.station_id)
        station.timezone = 'America/New_York'
        song = Track.query.one()
        song.title = '  =SUM(1,2)'
        song.artist = 'Björk, "Radio"\nLive'
        for index in range(260):
            db.session.add(SelectionDecision(station_id=station.id, track=song,
                status='started', started_at=stamp - timedelta(seconds=index)))
        for status in ('selected', 'queued', 'failed'):
            db.session.add(SelectionDecision(station_id=station.id, track=song, status=status))
        db.session.commit()
        expected = [r.id for r in SelectionDecision.query.filter_by(status='started').order_by(
            SelectionDecision.started_at.desc(), SelectionDecision.id.desc()).all()]
    response = client.get(BASE)
    result = rows(response)
    assert len(result) == 261
    assert [int(row['decision_id']) for row in result] == expected
    assert result[0]['title'] == "'  =SUM(1,2)"
    assert result[0]['artist'] == 'Björk, "Radio"\nLive'
    assert result[0]['started_at_local'] == '2026-11-01T01:30:00-05:00'
    assert result[0]['started_at_utc'] == '2026-11-01T06:30:00+00:00'
    assert 'charset=utf-8' in response.content_type
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'test-station-history.csv' in response.headers['Content-Disposition']
    empty = client.get('/admin/stations/second-station/history.csv')
    assert rows(empty) == [] and empty.text.startswith('decision_id,station,timezone,')
    assert client.get('/admin/history?station=test-station').text.count('Björk') == 100


def test_history_auth_missing_audio_and_event_fields(app):
    assert app.test_client().get(BASE).status_code == 302
    client = admin_client(app)
    with app.app_context():
        row = SelectionDecision.query.one()
        row.track = None
        row.relaxation = 'none'
        db.session.commit()
    result = rows(client.get(BASE))
    assert result[0]['title'] == 'Audio unavailable'
    assert result[0]['clock'] == 'Music Clock' and result[0]['rotation'] == 'Main Rotation'
    assert result[0]['slot'] == '1' and result[0]['timing_offset_seconds'] == ''
    assert 'Audio unavailable' in client.get('/admin/history?station=test-station').text
    assert client.get('/admin/stations/missing/history.csv').status_code == 404
    with app.app_context():
        AdminUser.query.one().role = 'DJ'
        db.session.commit()
    assert client.get(BASE).status_code == 403


def test_report_exports_keep_range_across_pages(app):
    client = admin_client(app)
    with app.app_context():
        original = SelectionDecision.query.one()
        original.started_at = datetime(2026, 3, 8, 6, tzinfo=timezone.utc)
        station = db.session.get(Station, original.station_id)
        station.timezone = 'America/New_York'
        for index in range(105):
            db.session.add(SelectionDecision(station_id=station.id, track_id=original.track_id,
                status='started', started_at=original.started_at + timedelta(seconds=index)))
        db.session.add(SelectionDecision(station_id=station.id, track_id=original.track_id,
            status='started', started_at=datetime(2026, 3, 9, 4, tzinfo=timezone.utc)))
        db.session.commit()
    query = '?range=custom&start=2026-03-08&end=2026-03-08'
    prefix = '/admin/stations/test-station/broadcast-reports'
    page = client.get(prefix + query + '&page=2')
    assert page.status_code == 200
    assert 'performances.csv?range=custom&amp;start=2026-03-08&amp;end=2026-03-08' in page.text
    data = list(csv.reader(io.StringIO(client.get(prefix + '/performances.csv' + query).text)))
    heading = next(i for i, row in enumerate(data) if row[0] == 'decision_id')
    assert len(data[heading+1:]) == 106
    for kind in ('tracks', 'summary'):
        assert client.get(prefix + '/' + kind + '.csv' + query).status_code == 200


def test_history_event_schedule_and_null_timing(app):
    client = admin_client(app)
    response = client.post('/admin/stations/test-station/external-bulletins', data=dict(
        csrf='test-admin-csrf-token', name='News', url='https://example.test/news.mp3',
        kind='FILE', duration=180, recurrence_type='HOURLY', local_time='00:00'))
    assert response.status_code == 303
    with app.app_context():
        occurrence = TimedEventOccurrence.query.first()
        occurrence.selection_decision = SelectionDecision.query.one()
        scheduled = occurrence.scheduled_for_utc.replace(tzinfo=timezone.utc)
        db.session.commit()
        identifier = occurrence.id
    result = rows(client.get(BASE))[0]
    assert result['event'] == 'News' and result['source'] == 'EVENT'
    assert result['scheduled_at_utc'] == scheduled.isoformat()
    assert result['timing_offset_seconds'] == ''
    assert client.get('/admin/history?station=test-station').status_code == 200
    with app.app_context():
        db.session.get(TimedEventOccurrence, identifier).started_at = scheduled + timedelta(seconds=2.5)
        db.session.commit()
    assert rows(client.get(BASE))[0]['timing_offset_seconds'] == '2.5'
