"""Opt-in production-database migration and concurrent station allocation."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import Station
from app.services.stations import create_station

pytestmark=pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'),reason='Requires a disposable PostgreSQL database')


def test_migration_preserves_existing_station_and_limit_serializes_empty_database(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    monkeypatch.setenv('SECRET_KEY','test-only')
    monkeypatch.setenv('FREO_MAX_STATIONS','3')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','f61c20d9a843'])
    assert result.exit_code==0,result.output
    with app.app_context():
        db.session.execute(text("INSERT INTO stations (name,slug,description,enabled,desired_state,timezone,target_lufs,created_at,updated_at) VALUES ('Existing','existing','',true,'stopped','UTC',-16,now(),now())"))
        db.session.commit()
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    with app.app_context():
        station=Station.query.one()
        assert station.name=='Existing' and station.lifecycle_state=='ready' and station.deleted_at is None
    result=runner.invoke(args=['db','downgrade','f61c20d9a843'])
    assert result.exit_code==0,result.output
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    with app.app_context():
        Station.query.delete();db.session.commit()
    barrier=Barrier(8)
    def create(index):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                create_station(f'Station {index}',f'concurrent-{index}')
                return True
            except ValueError as error:
                db.session.rollback()
                assert 'maximum of 3' in str(error)
                return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(create,range(8)))
    assert sum(results)==3
    with app.app_context():
        assert Station.query.count()==3
        # Slow filesystem/engine provisioning must not hold the allocation lock.
        from app.services import station_runtime as runtime
        from app.services.station_lifecycle import process_station
        from unittest.mock import Mock
        monkeypatch.setattr(runtime, 'ROOT', tmp_path)
        monkeypatch.setattr(runtime, 'require_root', lambda: None)
        monkeypatch.setattr(runtime, 'run_checked', Mock())
        monkeypatch.setattr('app.services.media._prepare_dirs', Mock())
        app.config['FREO_MAX_STATIONS'] = 0
        pending = create_station('Slow setup', 'slow-setup', pending=True)
        def render_while_allocating(station):
            def allocate():
                with app.app_context():
                    return create_station('Independent', 'independent').id
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(allocate).result(timeout=5)
        monkeypatch.setattr(runtime, 'render', render_while_allocating)
        process_station(pending)
        assert pending.lifecycle_state == 'ready'
        db.session.remove();db.engine.dispose()
