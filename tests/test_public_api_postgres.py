"""Full migrations and multi-connection limits on disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Barrier

import pytest
import sqlalchemy as sa
from app import create_app, models as m
from app.extensions import db
from app.services import public_api as service
from tests.test_schedule_postgres import pg_app

pytestmark = pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'), reason='Disposable PostgreSQL required')


@pytest.mark.parametrize('kind', ['network', 'credential'])
def test_atomic_limit_across_connections(pg_app, kind):
    barrier = Barrier(4)
    def hit(_):
        with pg_app.app_context():
            barrier.wait(timeout=10)
            return service.rate_limit(kind, 'concurrent', 2, now=6000)[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(hit, range(4)))
    assert sum(results) == 2
    with pg_app.app_context():
        assert m.ApiRateBucket.query.one().count == 2
        assert service.rate_limit(kind, 'concurrent', 2, now=6060)[0]


def test_migration_chain_phase5_data_and_revocation(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', 'f506a1b2c3d4'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        station = m.Station(name='Preserved', slug='preserved', request_settings={'enabled': True})
        user = m.AdminUser(email='api@example.test', password_hash='unused')
        db.session.add_all([station, user]); db.session.flush()
        db.session.add(m.ListenerRequest(station_id=station.id, status='expired', reason='Preserved',
            created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc)))
        db.session.add(m.SelectionDecision(station_id=station.id, status='started', reason='Preserved history',
            started_at=datetime.now(timezone.utc)))
        db.session.commit()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        row, token = service.create_credential(m.AdminUser.query.one(), 'PostgreSQL test', [m.Station.query.one().id])
        db.session.commit(); identifier = row.id
    client = app.test_client()
    assert client.get('/api/v1/stations', headers={'Authorization': 'Bearer ' + token}).status_code == 200
    with app.app_context():
        service.revoke_credential(m.AdminUser.query.one(), db.session.get(m.ApiCredential, identifier))
        db.session.commit()
    assert client.get('/api/v1/stations', headers={'Authorization': 'Bearer ' + token}).status_code == 401
    for command in (['db', 'downgrade', 'f506a1b2c3d4'], ['db', 'upgrade']):
        result = runner.invoke(args=command)
        assert result.exit_code == 0, result.output
    with app.app_context():
        assert m.Station.query.one().request_settings == {'enabled': True}
        assert m.ListenerRequest.query.one().reason == 'Preserved'
        assert m.SelectionDecision.query.one().reason == 'Preserved history'
        assert m.ApiCredential.query.count() == 0
        assert db.session.execute(sa.text('select version_num from alembic_version')).scalar() == 'f606a1b2c3d4'
