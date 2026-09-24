"""Current installer account migration on isolated, real PostgreSQL databases."""
import importlib
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg2.extensions import make_dsn, parse_dsn
import pytest
from sqlalchemy.engine import URL
from werkzeug.security import generate_password_hash

from freo_ops import recovery, releases
from freo_ops.upgrade import verify_preservation
from tests.test_recovery import postgres

OLD_REVISION = 'f39c8210b7de'
NEW_REVISION = 'a64f09e2b731'
PASSWORD = 'private migration fixture password'


@pytest.fixture
def installed(postgres, monkeypatch):
    from app import create_app
    from app.extensions import db

    _, new_database, _ = postgres
    source = new_database()
    params = parse_dsn(source)
    uri = URL.create('postgresql+psycopg2', username=params['user'], database=params['dbname'],
                     query={'host': params['host']})
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('DATABASE_URL', uri.render_as_string(hide_password=False))
    monkeypatch.setenv('SECRET_KEY', 'isolated-primary-admin-test')
    app = create_app('testing')
    result = app.test_cli_runner().invoke(args=['db', 'upgrade', OLD_REVISION])
    assert result.exit_code == 0, result.output
    yield app, source
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def seed(source, *, primary=True, active=True, granted=False, pending=False):
    con = recovery.connect(source)
    try:
        with con, con.cursor() as cur:
            # A secondary user is deliberately first: IDs/emails cannot select owner.
            for email, username, enabled, privilege, setup in [
                ('first@example.test', None, True, False, False),
                ('delegate@example.test', None, True, True, False),
                *([('owner@example.test', 'admin', active, granted, pending)] if primary else []),
            ]:
                cur.execute('INSERT INTO admin_users '
                    '(email,username,password_hash,active,installation_admin,setup_required,created_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,now())',
                    (email, username, generate_password_hash(PASSWORD), enabled, privilege, setup))
    finally:
        con.close()


def rows(source):
    con = recovery.connect(source)
    try:
        with con.cursor() as cur:
            cur.execute('SELECT row_to_json(u) FROM admin_users u ORDER BY id')
            return [row[0] for row in cur.fetchall()]
    finally:
        con.close()


def migrate(app):
    result = app.test_cli_runner().invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('options', [
    {}, {'granted': True}, {'active': False}, {'pending': True}, {'primary': False},
])
def test_only_installer_primary_receives_grant_and_other_values_survive(installed, options):
    from app.extensions import db

    app, source = installed
    seed(source, **options)
    expected = rows(source)
    for row in expected:
        if row['username'] == 'admin':
            row['installation_admin'] = True
    migrate(app)
    assert rows(source) == expected
    migrate(app)  # Alembic does not run the migration again.
    assert rows(source) == expected
    # The SQL itself is idempotent as well.
    module = importlib.import_module('migrations.versions.a64f09e2b731_primary_installation_admin')
    with app.app_context(), db.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    assert rows(source) == expected

    if options.get('primary', True):
        client = app.test_client()
        client.get('/admin/login')
        with client.session_transaction() as session:
            csrf = session['login_csrf']
        response = client.post('/admin/login', data={
            'email': 'owner@example.test', 'password': PASSWORD, 'csrf': csrf})
        page = client.get('/admin/software')
        if not options.get('active', True):
            assert response.status_code == 401
            assert page.status_code == 302 and page.location.endswith('/admin/login')
        elif options.get('pending', False):
            assert page.status_code == 302 and page.location.endswith('/admin/setup')
        else:
            assert page.status_code == 200
            assert 'Software and license' in page.text


def test_empty_install_keeps_existing_bootstrap_behavior(installed):
    from app.services.admin_setup import bootstrap
    from app.models import AdminUser

    app, source = installed
    migrate(app)
    assert rows(source) == []
    with app.app_context():
        assert bootstrap()
        user = AdminUser.query.one()
        assert user.username == 'admin' and user.installation_admin and user.setup_required


def test_completed_migration_does_not_regrant_on_later_upgrade(installed):
    app, source = installed
    seed(source)
    migrate(app)
    con = recovery.connect(source)
    try:
        with con, con.cursor() as cur:
            cur.execute("UPDATE admin_users SET installation_admin=false WHERE username='admin'")
        migrate(app)
        assert not next(row for row in rows(source) if row['username'] == 'admin')['installation_admin']
    finally:
        con.close()


def test_restored_backup_allows_only_exact_primary_grant(installed, postgres, tmp_path):
    from app.extensions import db

    app, source = installed
    target, _, created = postgres
    seed(source)
    original = rows(source)
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    state = tmp_path / 'state'
    state.mkdir()
    backup = tmp_path / 'before.gpg'
    recovery.create(source, [state], backup, b'isolated-fixture-key', version='0.3.0-rc.6')
    report = recovery.restore(backup, b'isolated-fixture-key', target, tmp_path / 'restored')
    created.append(report['database'])
    restored_params = parse_dsn(target)
    restored_params['dbname'] = report['database']
    restored = make_dsn(**restored_params)
    assert rows(restored) == original
    migrate(app)
    verify_preservation(source, restored)

    # Every other field/role remains protected, and a missing grant is rejected.
    changes = [
        ("UPDATE admin_users SET installation_admin=false WHERE username='admin'",
         "UPDATE admin_users SET installation_admin=true WHERE username='admin'"),
        ("UPDATE admin_users SET installation_admin=true WHERE email='first@example.test'",
         "UPDATE admin_users SET installation_admin=false WHERE email='first@example.test'"),
        ("UPDATE admin_users SET active=false WHERE username='admin'",
         "UPDATE admin_users SET active=true WHERE username='admin'"),
        ("UPDATE admin_users SET username='renamed' WHERE username='admin'",
         "UPDATE admin_users SET username='admin' WHERE username='renamed'"),
        ("UPDATE admin_users SET email='changed@example.test' WHERE username='admin'",
         "UPDATE admin_users SET email='owner@example.test' WHERE username='admin'"),
    ]
    con = recovery.connect(source)
    try:
        for change, undo in changes:
            with con, con.cursor() as cur:
                cur.execute(change)
            with pytest.raises(recovery.RecoveryError, match='pre-existing records'):
                verify_preservation(source, restored)
            with con, con.cursor() as cur:
                cur.execute(undo)
        with con, con.cursor() as cur:
            cur.execute("UPDATE admin_users SET password_hash='replaced' WHERE username='admin'")
        with pytest.raises(recovery.RecoveryError, match='pre-existing records'):
            verify_preservation(source, restored)
        with con, con.cursor() as cur:
            cur.execute("UPDATE admin_users SET password_hash=%s WHERE username='admin'",
                        (original[-1]['password_hash'],))
        verify_preservation(source, restored)
    finally:
        con.close()

    # Comparing two databases already at the new schema must not mask role changes.
    con = recovery.connect(restored)
    try:
        with con, con.cursor() as cur:
            cur.execute('UPDATE alembic_version SET version_num=%s', (NEW_REVISION,))
        with pytest.raises(recovery.RecoveryError, match='pre-existing records'):
            verify_preservation(source, restored)
    finally:
        con.close()


def test_release_schema_includes_primary_admin_migration():
    assert releases.migration_head(Path(__file__).resolve().parents[1]) == NEW_REVISION
