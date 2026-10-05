"""Disposable PostgreSQL migration and request serialization checks."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timezone
import uuid
import pytest
import sqlalchemy as sa
from app import create_app, models as m
from app.extensions import db
from app.services import listener_requests as r
from app.services.automation import select_next
from tests.test_schedule_postgres import pg_app

pytestmark = pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'), reason='Disposable PostgreSQL required')


def test_concurrent_submission_limits_and_selection_claim(pg_app, monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *a: '/safe')
    with pg_app.app_context():
        station = m.Station.query.one(); track = m.Track.query.one()
        station.request_settings = dict(r.DEFAULTS, enabled=True, delay_songs=0, station_limit=1)
        category = m.MediaCategory(station_id=station.id, name='Music', slug='music', tracks=[track])
        rotation = m.Rotation(station_id=station.id, name='Music', slug='music', slots=[m.RotationSlot(position=1, category=category)])
        db.session.add(rotation); db.session.flush(); station.automation.active_rotation_id = rotation.id
        db.session.commit(); track_uuid = track.uuid
    barrier = Barrier(2)
    def submit(index):
        with pg_app.app_context():
            station = m.Station.query.one(); barrier.wait(timeout=10)
            try:
                row = r.submit(station, track_uuid, str(index), str(uuid.uuid4())); db.session.commit(); return row.id
            except ValueError:
                db.session.rollback(); return None
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(submit, range(2)))
    assert sum(x is not None for x in results) == 1
    barrier = Barrier(2)
    def choose(_):
        with pg_app.app_context():
            barrier.wait(timeout=10)
            row = select_next('test-station'); return row.listener_request_id
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(choose, range(2)))
    assert sum(x is not None for x in results) == 1
    with pg_app.app_context():
        assert m.ListenerRequest.query.one().status == 'queued'
        assert m.SelectionDecision.query.filter(m.SelectionDecision.listener_request_id.isnot(None)).count() == 1


def test_full_migration_chain_and_phase5_roundtrip(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    app = create_app('testing'); runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade']); assert result.exit_code == 0, result.output
    with app.app_context():
        station = m.Station(name='Preserved', slug='preserved'); db.session.add(station); db.session.flush()
        db.session.add(m.SelectionDecision(station_id=station.id, status='started', reason='Preserved history', started_at=datetime.now(timezone.utc)))
        db.session.commit()
    for command in (['db', 'downgrade', 'f406a1b2c3d4'], ['db', 'upgrade']):
        result = runner.invoke(args=command); assert result.exit_code == 0, result.output
    with app.app_context():
        assert m.Station.query.one().name == 'Preserved'
        assert not r.settings(m.Station.query.one())['enabled']
        assert m.SelectionDecision.query.one().reason == 'Preserved history'
        db.session.remove(); db.drop_all(); db.session.execute(sa.text('DROP TABLE alembic_version')); db.session.commit()
