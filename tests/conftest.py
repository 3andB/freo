"""Keep opt-in PostgreSQL tests independent of previous migration/data state."""
from contextlib import contextmanager
import os
import uuid
import pytest
from sqlalchemy.engine import make_url
from psycopg2 import sql
from freo_ops.recovery import connect


@contextmanager
def disposable_database():
    url = os.environ['FREO_TEST_POSTGRES_URL']
    name = 'freo_test_' + uuid.uuid4().hex
    connection = connect(url)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
        yield make_url(url).set(database=name).render_as_string(hide_password=False)
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        connection.close()


@pytest.fixture(scope='module')
def station_postgres_database():
    # The station module intentionally tests a migration followed by operations
    # on the migrated station. Keep that lifecycle together in its own database.
    with disposable_database() as url:
        yield url


@pytest.fixture(autouse=True)
def isolate_postgres(request, monkeypatch):
    if not os.environ.get('FREO_TEST_POSTGRES_URL') or not request.path.name.endswith('_postgres.py'):
        yield
    elif request.path.name == 'test_station_postgres.py':
        monkeypatch.setenv('FREO_TEST_POSTGRES_URL', request.getfixturevalue('station_postgres_database'))
        yield
    else:
        with disposable_database() as url:
            monkeypatch.setenv('FREO_TEST_POSTGRES_URL', url)
            yield


@pytest.fixture(autouse=True)
def isolated_hosting_policy(tmp_path, monkeypatch):
    """Unit/regression suites never inherit the test host's real commercial policy."""
    from freo_ops import hosting
    monkeypatch.setattr(hosting, 'CONFIG', tmp_path / 'absent-hosting.json')
    monkeypatch.setattr(hosting, 'STATE', tmp_path / 'absent-hosting-authority')
