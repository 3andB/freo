"""Upgrade a populated installer schema through both pending migrations."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from alembic.script import ScriptDirectory
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.extensions import db
from app.models import Station
from freo_ops import recovery
from tests.test_recovery import postgres
from tests.test_primary_admin_migration import installed, seed, rows, migrate


def test_both_migrations_preserve_station_identity_and_restart_state(installed):
    app, source = installed
    seed(source)
    station_ids = [str(uuid4()), str(uuid4())]
    con = recovery.connect(source)
    try:
        with con, con.cursor() as cur:
            for index, identity in enumerate(station_ids):
                cur.execute("""INSERT INTO stations
                    (name,slug,description,enabled,desired_state,timezone,target_lufs,created_at,updated_at,
                     freo_station_id,city,region,country)
                    VALUES (%s,%s,'Preserved station',true,'running','UTC',-16,now(),now(),%s,%s,%s,%s)""",
                    (f'Station {index}', f'station-{index}', identity,
                     'New York' if index == 0 else '', 'NY' if index == 0 else '', 'US' if index == 0 else ''))
            cur.execute('SELECT row_to_json(s) FROM stations s ORDER BY id')
            original = [row[0] for row in cur.fetchall()]
        migrate(app)
        with con.cursor() as cur:
            cur.execute('SELECT version_num FROM alembic_version')
            assert cur.fetchone()[0] == 'c83d4e5f9012'
            cur.execute('SELECT row_to_json(s) FROM stations s ORDER BY id')
            assert [r[0] for r in cur.fetchall()] == [dict(r, latitude=None, longitude=None) for r in original]
        assert next(r for r in rows(source) if r['username'] == 'admin')['installation_admin']
        with app.app_context():
            # Compare this migration's table. The historical full schema has an
            # unrelated ix_event_due index absent from TimedEventOccurrence metadata.
            with db.engine.connect() as connection:
                context = MigrationContext.configure(connection, opts={
                    'include_object': lambda obj, name, kind, reflected, compare_to:
                        name == 'stations' if kind == 'table' else obj.table.name == 'stations',
                })
                assert compare_metadata(context, db.metadata) == []
            first = Station.query.order_by(Station.id).first()
            first.latitude, first.longitude = 40.7128, -74.006
            db.session.commit()
            db.session.remove()
            db.engine.dispose()
        # Fresh application/connection models a restart, using the same test DB.
        restarted = create_app('testing')
        with restarted.app_context():
            stations = Station.query.order_by(Station.id).all()
            assert [s.freo_station_id for s in stations] == station_ids
            assert (stations[0].latitude, stations[0].longitude) == (40.71, -74.01)
            assert stations[1].latitude is None and stations[1].longitude is None
            # Direct SQL cannot introduce invalid or partial stored locations.
            for latitude, longitude in [(None, 1), (1, None), (91, 0), (0, -181),
                                         (float('nan'), 0), (0, float('inf'))]:
                with pytest.raises(IntegrityError) as error:
                    db.session.execute(text('UPDATE stations SET latitude=:lat, longitude=:lon WHERE id=:id'),
                        dict(lat=latitude, lon=longitude, id=stations[0].id))
                    db.session.commit()
                assert 'ck_stations_coordinates' in str(error.value)
                db.session.rollback()
            db.session.remove()
            db.engine.dispose()
        migrate(app)
    finally:
        con.close()


def test_location_migration_follows_approved_admin_migration():
    cfg = Config()
    cfg.set_main_option('script_location', 'migrations')
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ['c83d4e5f9012']
    assert script.get_revision('c83d4e5f9012').down_revision == 'b72e19d4c603'
    assert script.get_revision('b72e19d4c603').down_revision == 'a64f09e2b731'
    assert script.get_revision('a64f09e2b731').down_revision == 'f39c8210b7de'


def test_upgrade_from_admin_migration_does_not_regrant_a_revoked_permission(installed):
    app, source = installed
    seed(source)
    result = app.test_cli_runner().invoke(args=['db', 'upgrade', 'a64f09e2b731'])
    assert result.exit_code == 0, result.output
    con = recovery.connect(source)
    try:
        with con, con.cursor() as cur:
            cur.execute("UPDATE admin_users SET installation_admin=false WHERE username='admin'")
        before = rows(source)
        migrate(app)
        assert rows(source) == before
    finally:
        con.close()
