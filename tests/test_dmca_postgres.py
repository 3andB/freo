"""Opt-in migration and concurrency checks on a disposable PostgreSQL database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import MetaData, Table, inspect, text
from app import create_app
from app.extensions import db
from app.models import DMCACase, Station, Track
from tests.test_recovery import postgres

pytestmark = pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'), reason='Requires a disposable PostgreSQL database')


def test_security_downgrade_refuses_and_matched_recovery_restores(postgres, monkeypatch, tmp_path):
    from pathlib import Path
    from sqlalchemy.engine import make_url
    from freo_ops import recovery
    from app.version import VERSION
    target_url, new_database, created = postgres
    # Use a SQLAlchemy URL while keeping the recovery fixture's database cleanup.
    from psycopg2.extensions import parse_dsn
    source_url = make_url(target_url).set(database=parse_dsn(new_database())['dbname']).render_as_string(hide_password=False)
    monkeypatch.setenv('DATABASE_URL', source_url)
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'recovery-test-only')
    app = create_app('testing')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.add(Station(name='Before recovery', slug='recover'))
        db.session.commit()
        db.session.remove(); db.engine.dispose()
    state = tmp_path / 'state'; state.mkdir()
    (state / 'version.py').write_bytes((Path(__file__).parents[1] / 'app/version.py').read_bytes())
    (state / '.env').write_text('SECRET_KEY=recovery-test-only\n')
    bundle = tmp_path / 'matched.gpg'
    saved = recovery.create(source_url, [state], bundle, b'test-recovery-passphrase', version=VERSION)
    refused = runner.invoke(args=['db', 'downgrade', 'f84c1d92be30'])
    assert refused.exit_code != 0 and 'matched recovery point' in refused.output
    with app.app_context():
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == saved['schema_revision']
        assert 'expires_at' in {c['name'] for c in inspect(db.engine).get_columns('admin_login_sessions')}
        Station.query.one().name = 'After snapshot'; db.session.commit()
        db.session.remove(); db.engine.dispose()
    (state / '.env').write_text('SECRET_KEY=changed-after-snapshot\n')
    restored = recovery.restore(bundle, b'test-recovery-passphrase', target_url, tmp_path / 'restored')
    created.append(restored['database'])
    assert restored['status'] == 'verified' and restored['version'] == VERSION
    assert restored['schema_revision'] == saved['schema_revision']
    assert (tmp_path / 'restored/root-0/.env').read_text() == 'SECRET_KEY=recovery-test-only\n'
    assert (tmp_path / 'restored/root-0/version.py').read_bytes() == (state / 'version.py').read_bytes()
    restored_url = make_url(target_url).set(database=restored['database']).render_as_string(hide_password=False)
    connection = recovery.connect(restored_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT name FROM stations'); assert cursor.fetchone()[0] == 'Before recovery'
            cursor.execute('SELECT expires_at FROM admin_login_sessions LIMIT 1')
    finally:
        connection.close()


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
    # Seed the historical schema directly: today's ORM has newer columns.
    migrate('upgrade', 'f84c1d92be30')
    with app.app_context():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stations = Table('stations', MetaData(), autoload_with=db.engine)
        tracks = Table('tracks', MetaData(), autoload_with=db.engine)
        station_id = db.session.execute(stations.insert().values(name='Evidence station', slug='evidence',
            description='', enabled=True, desired_state='stopped', timezone='UTC', target_lufs=-16,
            created_at=now, updated_at=now).returning(stations.c.id)).scalar_one()
        values = dict(station_id=station_id, uuid='legacy', title='Original title', artist='Original artist',
            album='', original_filename='test.mp3', storage_key='test.mp3', media_type='mp3', duration_ms=1000,
            sample_rate_hz=44100, channels=2, file_size_bytes=1234, checksum_sha256='a'*64, isrc='legacy-isrc',
            enabled=True, ingest_status='accepted', created_at=now, updated_at=now)
        identifier = db.session.execute(tracks.insert().values(**values).returning(tracks.c.id)).scalar_one()
        db.session.commit()
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
