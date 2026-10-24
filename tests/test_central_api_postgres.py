"""Opt-in checks against an explicitly disposable PostgreSQL database."""
import os
from uuid import UUID
import pytest
from sqlalchemy import inspect, text
from app import create_app
from app.extensions import db
from app.models import Station

pytestmark = pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'), reason='Requires disposable PostgreSQL')


def test_station_uuid_migration_and_schema(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing')
    runner = app.test_cli_runner()
    def migrate(*args):
        result = runner.invoke(args=['db', *args])
        assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
    migrate('upgrade', 'c07d9a21b634')
    with app.app_context():
        db.session.execute(text("""INSERT INTO stations
            (name, slug, description, enabled, desired_state, timezone, target_lufs, created_at, updated_at)
            VALUES ('Legacy', 'legacy', '', true, 'running', 'UTC', -16, now(), now())"""))
        db.session.commit()
    migrate('upgrade')
    migrate('check')
    with app.app_context():
        index = next(i for i in inspect(db.engine).get_indexes('timed_event_occurrences') if i['name'] == 'ix_event_due')
        assert index['column_names'] == ['station_id', 'state', 'scheduled_for_utc']
        assert not index['unique']
        station = Station.query.one()
        identity = station.freo_station_id
        assert UUID(identity).version == 4
        assert station.desired_state == 'running' and station.enabled
        assert not station.directory_opt_in and station.country == ''
        station.name = 'Renamed'
        db.session.commit()
    migrate('upgrade')
    with app.app_context():
        assert Station.query.one().freo_station_id == identity
    refused = runner.invoke(args=['db', 'downgrade', 'c07d9a21b634'])
    assert refused.exit_code != 0 and 'matched recovery point' in refused.output
    migrate('upgrade')
    migrate('check')


def test_license_channel_limit_serializes_concurrent_enables(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.models import CentralInstallation
    from app.services.stations import set_enabled
    from tests.test_central_api import license_payload
    import time
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    application = create_app('testing')
    with application.app_context():
        db.drop_all()
        db.create_all()
        payload = license_payload(channel_limit=1)
        db.session.add(CentralInstallation(id=1, manager_email='manager@example.org',
            installation_id=payload['installation_id'], registration_state='registered',
            license_cache={'entitlement': payload, 'received_at': time.time(), 'checked_at': time.time()}))
        # A stale remote one-station quota cannot restrict the local free tier.
        db.session.add_all([Station(name='One', slug='one'), Station(name='Two', slug='two')])
        db.session.add_all([Station(name='Three', slug='three', enabled=False), Station(name='Four', slug='four', enabled=False)])
        db.session.commit()
        ids = [station.id for station in Station.query.filter_by(enabled=False)]
    barrier = Barrier(2)
    def enable(station_id):
        with application.app_context():
            station = db.session.get(Station, station_id)
            barrier.wait(timeout=10)
            try:
                set_enabled(station, True)
                return True
            except ValueError as error:
                db.session.rollback()
                assert 'three stations' in str(error)
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(enable, ids)) == [False, True]
    with application.app_context():
        assert Station.query.filter_by(enabled=True).count() == 3


def test_reporting_provenance_migration_preserves_existing_identity_and_hours(monkeypatch):
    import json
    import time
    from app.models import CentralInstallation, CentralHourlyMetric
    from app.services.central_api.metrics import wire_metric
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    application = create_app('testing')
    runner = application.test_cli_runner()
    with application.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
    result = runner.invoke(args=['db', 'upgrade', 'fc06a1b2c3d4'])
    assert result.exit_code == 0, result.output
    identity = 'cbeb636f-2565-4876-8d1a-80294d663c8c'
    hour = int(time.time() // 3600) * 3600 - 3600
    with application.app_context():
        station = Station(name='Retained reporting fixture', slug='retained-reporting')
        db.session.add(station)
        db.session.add(CentralInstallation(id=1, installation_id=identity,
            registration_state='enrolled', state={'report': {'due': 123}, 'owner_profile_id': 'retained-owner'},
            license_cache={'fixture': 'retain exactly'}))
        db.session.flush()
        station_id, station_uuid = station.id, station.freo_station_id
        snapshot = json.dumps(dict(current_listeners=2, stream_running=True))
        for offset, coverage in ((0, 60), (3600, 0)):
            db.session.execute(text('INSERT INTO central_hourly_metrics '
                '(station_id, period_start, observed_seconds, listener_seconds, peak_listeners, snapshot, sent) '
                'VALUES (:station, :hour, :coverage, :listeners, 2, CAST(:snapshot AS JSON), false)'),
                dict(station=station_id, hour=hour-offset, coverage=coverage, listeners=coverage*2, snapshot=snapshot))
        db.session.commit()
        before = db.session.execute(text('SELECT * FROM central_installation')).one()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=['db', 'check'])
    assert result.exit_code == 0, result.output
    with application.app_context():
        assert db.session.execute(text('SELECT * FROM central_installation')).one() == before
        assert db.session.get(Station, station_id).freo_station_id == station_uuid
        known = db.session.get(CentralHourlyMetric, (station_id, hour))
        unknown = db.session.get(CentralHourlyMetric, (station_id, hour-3600))
        assert known.coverage is None and unknown.coverage is None
        assert wire_metric(known, True)['observed_seconds'] == 60
        assert wire_metric(unknown, True)['observed_seconds'] is None
        assert known.snapshot == unknown.snapshot == json.loads(snapshot)
        assert known.listener_seconds == 120 and not known.sent and not unknown.sent
