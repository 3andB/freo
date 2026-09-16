"""Opt-in checks against an explicitly disposable PostgreSQL database."""
import os
from uuid import UUID
import pytest
from sqlalchemy import text
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
    migrate('downgrade', 'c07d9a21b634')
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
        db.session.add_all([Station(name='One', slug='one', enabled=False), Station(name='Two', slug='two', enabled=False)])
        db.session.commit()
        ids = [station.id for station in Station.query]
    barrier = Barrier(2)
    def enable(station_id):
        with application.app_context():
            station = db.session.get(Station, station_id)
            barrier.wait(timeout=10)
            try:
                set_enabled(station, True)
                return True
            except ValueError:
                db.session.rollback()
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(enable, ids)) == [False, True]
    with application.app_context():
        assert Station.query.filter_by(enabled=True).count() == 1
