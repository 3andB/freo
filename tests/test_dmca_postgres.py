"""Opt-in migration and concurrency checks on a disposable PostgreSQL database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import DMCACase, Station, Track

pytestmark = pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'), reason='Requires a disposable PostgreSQL database')


def test_migration_backfill_constraints_evidence_and_concurrent_reports(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing')
    runner = app.test_cli_runner()
    # Caller explicitly supplies a disposable database, as in test_station_postgres.
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
    def migrate(*args):
        result = runner.invoke(args=['db', *args])
        assert result.exit_code == 0, result.output
    migrate('upgrade')
    with app.app_context():
        station = Station(name='Evidence station', slug='evidence')
        db.session.add(station); db.session.flush()
        track = Track(station_id=station.id, uuid='legacy', title='Original title', artist='Original artist',
                      original_filename='test.mp3', storage_key='test.mp3', media_type='mp3',
                      duration_ms=1000, sample_rate_hz=44100, channels=2, file_size_bytes=1234,
                      checksum_sha256='a'*64, isrc='legacy-isrc')
        db.session.add(track); db.session.commit()
        identifier, station_id = track.id, station.id
    migrate('downgrade', 'f84c1d92be30')
    migrate('upgrade')
    migrate('check')
    with app.app_context():
        track = db.session.get(Track, identifier)
        assert track.freo_track_id.startswith('FR-')
        assert track.title == 'Original title' and track.isrc == 'legacy-isrc'
        assert track.checksum_sha256 == 'a'*64
        public_id = track.freo_track_id
    app.config['DMCA_REPORTS_PER_HOUR'] = 2
    barrier = Barrier(6)
    def send(_):
        client = app.test_client()
        client.get('/dmca')
        with client.session_transaction() as session:
            csrf = session['admin_csrf']
        barrier.wait(timeout=10)
        return client.post('/dmca', data=dict(csrf=csrf, supplied_track_id=public_id,
            station_text='Evidence station', copyrighted_work='My work', material_location='The broadcast',
            claimant_name='Claimant', claimant_email='claimant@example.test', signature='Claimant',
            good_faith='yes', authorized='yes')).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(send, range(6)))
    assert sorted(results) == [201, 201, 429, 429, 429, 429]
    with app.app_context():
        assert DMCACase.query.count() == 2
        # Exercise actual PostgreSQL ON DELETE SET NULL, not SQLite's optional FK mode.
        db.session.execute(text('DELETE FROM tracks WHERE id=:id'), {'id': identifier})
        db.session.execute(text('DELETE FROM stations WHERE id=:id'), {'id': station_id})
        db.session.commit(); db.session.expire_all()
        for row in DMCACase.query.all():
            assert row.track_id is None and row.station_id is None and row.reported_station_id is None
            assert row.snapshot['title'] == 'Original title'
            assert row.snapshot['sha256'] == 'a'*64
        db.session.remove()
        db.drop_all()
        db.session.execute(text('DROP TABLE alembic_version'))
        db.session.commit()
