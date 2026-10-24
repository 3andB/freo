"""Real PostgreSQL predicates for every root provisioning work category."""
import os
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from freo_ops import provision_pending


pytestmark = pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'),
                                reason='Requires a disposable PostgreSQL database')


@pytest.fixture
def pending_database(monkeypatch):
    url = os.environ['FREO_TEST_POSTGRES_URL']
    schema = 'provision_guard_' + uuid.uuid4().hex
    with psycopg2.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            cursor.execute('CREATE TABLE stations (lifecycle_state text, broadcast_status text, '
                           'internet_radio_status text, deleted_at timestamptz)')
            cursor.execute('CREATE TABLE stream_mounts (audio_status text)')
    params = parse_dsn(url)
    params['options'] = '-csearch_path=' + schema
    private_url = make_dsn(**params)
    monkeypatch.setenv('DATABASE_URL', private_url)
    try:
        yield private_url
    finally:
        with psycopg2.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.mark.parametrize('column,state', [
    ('lifecycle_state', 'pending_create'), ('lifecycle_state', 'pending_delete'),
    ('broadcast_status', 'pending'), ('broadcast_status', 'applying'),
    ('internet_radio_status', 'pending'), ('internet_radio_status', 'applying'),
    ('audio_status', 'pending'), ('audio_status', 'applying'),
])
def test_each_pending_operation_runs_worker(pending_database, column, state):
    assert provision_pending.main() == 1
    table = 'stream_mounts' if column == 'audio_status' else 'stations'
    with psycopg2.connect(pending_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('INSERT INTO {} ({}) VALUES (%s)').format(
                sql.Identifier(table), sql.Identifier(column)), (state,))
    assert provision_pending.main() == 0


def test_terminal_rows_and_retired_broadcast_do_not_wake_worker(pending_database):
    with psycopg2.connect(pending_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO stations VALUES ('ready','ready','ready',NULL),"
                           "('create_failed','failed','failed',NULL),"
                           "('deleted','pending','ready',now())")
            cursor.execute("INSERT INTO stream_mounts VALUES ('ready'),('failed')")
    assert provision_pending.main() == 1


def test_database_failure_is_reported_without_credentials(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise RuntimeError('postgresql://private:secret@example.invalid')
    monkeypatch.setenv('DATABASE_URL', 'private')
    monkeypatch.setattr(provision_pending.psycopg2, 'connect', unavailable)
    assert provision_pending.main() == 255
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'Provisioning work check failed; inspect database availability.\n'


def test_sqlalchemy_driver_url_preserves_authenticated_connection(pending_database, monkeypatch):
    from sqlalchemy.engine import URL
    params = parse_dsn(pending_database)
    url = URL.create('postgresql+psycopg2', username=params.get('user'),
        password=params.get('password'), host=params.get('host'),
        port=int(params['port']) if params.get('port') else None,
        database=params.get('dbname'), query={'options': params['options']})
    monkeypatch.setenv('DATABASE_URL', url.render_as_string(hide_password=False))
    assert provision_pending.main() == 1


def test_missing_schema_is_an_error_not_an_idle_skip(pending_database, capsys):
    with psycopg2.connect(pending_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE stations, stream_mounts')
    assert provision_pending.main() == 255
    assert capsys.readouterr().err.startswith('Provisioning work check failed;')
