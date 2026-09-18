import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_cue_migration_preserves_catalog_and_roundtrips(tmp_path):
    engine = sa.create_engine(f'sqlite:///{tmp_path}/migration.sqlite')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE stations (id INTEGER PRIMARY KEY, name VARCHAR(100))'))
        connection.execute(sa.text('CREATE TABLE selection_decisions (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text("INSERT INTO stations VALUES (1, 'Existing station')"))
        spec = importlib.util.spec_from_file_location('cue_migration', 'migrations/versions/ab28c910d642_booth_cue_lists.py')
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(sa.text("INSERT INTO booth_cues VALUES (1, 1, 'generation', 'Set', '[]', NULL, '[]', false, false, 'A', '')"))
            assert connection.execute(sa.text('SELECT name FROM booth_cues')).scalar() == 'Set'
            migration.downgrade()
            migration.upgrade()
        assert connection.execute(sa.text('SELECT name FROM stations')).scalar() == 'Existing station'
    engine.dispose()
