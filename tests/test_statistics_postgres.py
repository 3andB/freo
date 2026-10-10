"""Analytics migration and collector serialization on a disposable PostgreSQL DB."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import AudiencePresence, SessionBucket, Station, StatsState
from app.services.statistics import sessions
from tests.test_statistics_sessions import tick
from tests.test_schedule_postgres import pg_app

pytestmark = pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'), reason='Disposable PostgreSQL required')


def test_listener_migration_preserves_history(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    app = create_app('testing')
    runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', 'f316a1b2c3d4'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.execute(text("INSERT INTO stats_presence(scope,source,key,first_seen,last_seen,geo) VALUES (1,'stream','legacy',100,200,'{}')"))
        db.session.add(StatsState(scope=1, data=dict(at=200, sessions_since=100,
                                                 session_clients_at=200, session_clients_valid=True)))
        db.session.commit()
    for args in (['db', 'upgrade'], ['db', 'downgrade', 'f316a1b2c3d4'], ['db', 'upgrade']):
        result = runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        row = AudiencePresence.query.one()
        assert (row.first_seen, row.last_seen, row.listening) == (100, 200, None)
        assert db.session.execute(text('SELECT data FROM stats_states WHERE scope=1')).scalar() == {'at': 200}
        db.session.add(Station(id=1, name='Migration', slug='migration'))
        db.session.commit()
        tick(3600, ['one'])
        tick(3615, ['one'])
        tick(3630, [])
        data = sessions.report(1, 3600, 3660, 3660)['sessions']
        assert data['completed'] == 1 and data['average_seconds'] == 15


def test_simultaneous_collector_retries_finalize_once(pg_app):
    with pg_app.app_context():
        tick(3600, ['one'])
        tick(3615, ['one'])
    barrier = Barrier(2)
    def attempt(_):
        with pg_app.app_context():
            barrier.wait(timeout=10)
            tick(3630, [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(attempt, range(2)))
    with pg_app.app_context():
        bucket = SessionBucket.query.filter_by(scope=1, at=3600).one()
        assert bucket.data['starts'] == 1 and bucket.data['completed'] == 1
        assert bucket.data['duration_seconds'] == 15
