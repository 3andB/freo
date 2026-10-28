"""Exercise the populated RC15 -> RC16 migration on real PostgreSQL."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
import pytest
from psycopg2.extensions import make_dsn, parse_dsn
from freo_ops.upgrade import verify_preservation
from app.extensions import db
from app.models import Station
from freo_ops import recovery
from tests.test_primary_admin_migration import installed, migrate
from tests.test_recovery import postgres


def test_consent_migration_preserves_optouts_identities_and_restarts(installed, postgres, tmp_path):
    app, source = installed
    migrate(app, 'fd17b2c3d4e5')
    con = recovery.connect(source)
    try:
        with con, con.cursor() as cur:
            for index, consent in enumerate([False, False, True]):
                cur.execute("""INSERT INTO stations
                    (name,slug,description,enabled,desired_state,timezone,target_lufs,created_at,updated_at,
                     freo_station_id,directory_opt_in)
                    VALUES (%s,%s,'Kept',true,'running','UTC',-16,now(),now(),%s,%s) RETURNING id""",
                    ('Station '+str(index), 'migration-'+str(index), '00000000-0000-4000-8000-00000000000'+str(index), consent))
                station_id = cur.fetchone()[0]
                if index == 1:
                    cur.execute("""INSERT INTO audit_events(station_id,action,target_type,summary,created_at)
                                   VALUES (%s,'station_details_updated','station','Old settings save',now())""", (station_id,))
                cur.execute("INSERT INTO central_station_state(station_id,synced_digest) VALUES (%s,'old')", (station_id,))
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        con.close()
        target, _, created = postgres
        state = tmp_path / 'state'
        state.mkdir()
        backup = tmp_path / 'before.gpg'
        recovery.create(source, [state], backup, b'isolated-fixture-key', version='1.0.0-rc.15')
        report = recovery.restore(backup, b'isolated-fixture-key', target, tmp_path / 'restored')
        created.append(report['database'])
        params = parse_dsn(target)
        params['dbname'] = report['database']
        restored = make_dsn(**params)
        migrate(app)
        con = recovery.connect(source)
        verify_preservation(source, restored)
        with con, con.cursor() as cur:
            cur.execute("UPDATE stations SET directory_opt_in=true WHERE slug='migration-1'")
        with pytest.raises(recovery.RecoveryError, match='pre-existing records'):
            verify_preservation(source, restored)
        with con, con.cursor() as cur:
            cur.execute("UPDATE stations SET directory_opt_in=false WHERE slug='migration-1'")
        with app.app_context():
            stations = Station.query.order_by(Station.id).all()
            assert [s.directory_opt_in for s in stations] == [True, False, True]
            assert [s.directory_consent_source for s in stations] == ['migrated_default_on', 'legacy_preserved_off', 'legacy_on']
            assert all(s.desired_state == 'running' and s.description == 'Kept' for s in stations)
            assert [s.freo_station_id for s in stations] == ['00000000-0000-4000-8000-00000000000'+str(i) for i in range(3)]
            assert not any(db.session.execute(text('SELECT synced_digest FROM central_station_state')).scalars())
            with db.engine.connect() as connection:
                context = MigrationContext.configure(connection, opts={'include_object': lambda obj, name, kind, reflected, compare_to:
                    name == 'stations' if kind == 'table' else obj.table.name == 'stations'})
                assert compare_metadata(context, db.metadata) == []
            stations[0].directory_opt_in = False
            stations[0].directory_consent_source = 'explicit'
            db.session.commit()
            db.session.remove()
        migrate(app)
        with app.app_context():
            assert not Station.query.order_by(Station.id).first().directory_opt_in
    finally:
        con.close()
