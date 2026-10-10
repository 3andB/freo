"""Additive import migration preserves populated catalogs in SQLite/PostgreSQL."""
import importlib.util
import os
import uuid
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize('backend',['sqlite','postgres'])
def test_import_migration_roundtrip(tmp_path,backend):
    url=f'sqlite:///{tmp_path}/migration.sqlite' if backend=='sqlite' else os.getenv('FREO_TEST_POSTGRES_URL')
    if not url:pytest.skip('Use scripts/test-import-postgres.sh for isolated PostgreSQL')
    engine=sa.create_engine(url)
    schema='import_migration_'+uuid.uuid4().hex if backend=='postgres' else None
    with engine.begin() as connection:
        if schema:
            connection.execute(sa.text(f'CREATE SCHEMA {schema}'))
            connection.execute(sa.text(f'SET search_path TO {schema}'))
        for table in ('stations','admin_users','media_ingest_jobs'):
            kind='VARCHAR(36)' if table=='media_ingest_jobs' else 'INTEGER'
            connection.execute(sa.text(f'CREATE TABLE {table} (id {kind} PRIMARY KEY, marker VARCHAR(100))'))
        connection.execute(sa.text("INSERT INTO stations VALUES(1,'Existing station')"))
        connection.execute(sa.text("INSERT INTO admin_users VALUES(1,'Existing user')"))
        connection.execute(sa.text("INSERT INTO media_ingest_jobs VALUES('old-job','Existing job')"))
        spec=importlib.util.spec_from_file_location('import_migration','migrations/versions/e92b740a613f_music_import_sessions.py')
        migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(sa.text("INSERT INTO music_import_sessions(id,station_id,admin_user_id,created_at,updated_at,groups) VALUES('draft',1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'{}')"))
            connection.execute(sa.text("INSERT INTO music_import_items(id,session_id,original_filename,relative_path,size_bytes,checksum,status,detected,choices,revision,error,dismissed,created_at) VALUES('item','draft','song.mp3','',10,'digest','ready','{}','{}',1,'',false,CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError,match='Finish or cancel'):migration.downgrade()
            connection.execute(sa.text("UPDATE music_import_items SET status='cancelled'"))
            migration.downgrade();migration.upgrade()
        assert connection.execute(sa.text('SELECT marker FROM stations')).scalar()=='Existing station'
        assert connection.execute(sa.text('SELECT marker FROM media_ingest_jobs')).scalar()=='Existing job'
        if schema:connection.execute(sa.text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()
