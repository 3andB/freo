"""Event edits and the worker must acquire station/occurrence locks in order."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
import sqlalchemy as sa
from app import models as m
from app.extensions import db
from app.automation_worker import EventReader, process_timed_events
from app.services.timed_events import save_event, set_enabled
from tests.test_schedule_postgres import pg_app

pytestmark = pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'),
                              reason='Disposable PostgreSQL required')


def test_disabling_future_event_during_worker_scan_does_not_deadlock(pg_app, monkeypatch):
    from app.services.media_storage import LocalMediaStorage
    monkeypatch.setattr(LocalMediaStorage, 'regular_file', lambda *args: '/safe')
    now = datetime.now(timezone.utc)
    scheduled = now + timedelta(minutes=5)
    with pg_app.app_context():
        station = m.Station.query.one()
        event = save_event(station.slug, name='Concurrent disable', recurrence_type='ONE_TIME',
            local_date=scheduled.date().isoformat(), local_time=scheduled.strftime('%H:%M'),
            content_type='TRACK', content_identifier=m.Track.query.one().uuid)
        identifier = event.id
        engine = db.engine
    scanned, resume, editor_connected = Event(), Event(), Event()
    editor_pid = []

    def worker():
        with pg_app.app_context():
            station = m.Station.query.one()
            process_timed_events(station, EventReader(), now)
            scanned.set()
            assert resume.wait(10)
            # The ordinary selector takes this lock after the event scan.
            db.session.query(m.Station.id).filter_by(id=station.id).with_for_update().one()
            db.session.commit()

    def editor():
        assert scanned.wait(10)
        with pg_app.app_context():
            editor_pid.append(db.session.execute(sa.text('SELECT pg_backend_pid()')).scalar_one())
            editor_connected.set()
            set_enabled(db.session.get(m.TimedEvent, identifier), False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        working, editing = pool.submit(worker), pool.submit(editor)
        try:
            assert editor_connected.wait(10)
            deadline = time.monotonic()+5
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                while time.monotonic() < deadline:
                    waiting = conn.execute(sa.text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),
                                           {'pid': editor_pid[0]}).scalar_one()
                    if waiting == 'Lock':
                        break
                    time.sleep(.02)
                else:
                    pytest.fail('Concurrent edit did not reach the station/occurrence lock')
        finally:
            resume.set()
        working.result(timeout=10)
        editing.result(timeout=10)
    with pg_app.app_context():
        event = db.session.get(m.TimedEvent, identifier)
        assert not event.enabled
        assert all(row.state == 'CANCELLED' for row in event.occurrences)


def test_event_disabled_after_listing_is_not_prepared(pg_app, monkeypatch):
    from app.services import timed_events
    from app.services.media_storage import LocalMediaStorage
    monkeypatch.setattr(LocalMediaStorage, 'regular_file', lambda *args: '/safe')
    now = datetime.now(timezone.utc)
    scheduled = now + timedelta(minutes=1)
    with pg_app.app_context():
        station = m.Station.query.one()
        event = save_event(station.slug, name='Disable before preparation', recurrence_type='ONE_TIME',
            local_date=scheduled.date().isoformat(), local_time=scheduled.strftime('%H:%M'),
            content_type='TRACK', content_identifier=m.Track.query.one().uuid)
        identifier = event.id
    original = timed_events.upcoming

    def disable():
        with pg_app.app_context():
            set_enabled(db.session.get(m.TimedEvent, identifier), False)

    def listed(*args, **kwargs):
        rows = original(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(disable).result(timeout=10)
        return rows

    monkeypatch.setattr(timed_events, 'upcoming', listed)
    with pg_app.app_context():
        process_timed_events(m.Station.query.one(), EventReader(), now)
        db.session.commit()
        event = db.session.get(m.TimedEvent, identifier)
        assert not event.enabled
        assert all(row.state == 'CANCELLED' and row.selection_decision_id is None for row in event.occurrences)
        assert m.SelectionDecision.query.count() == 0
