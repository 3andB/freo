"""The login revocation migration adds no permissions or account changes."""
from tests.test_primary_admin_migration import installed, seed, rows
from tests.test_recovery import postgres
from app.extensions import db
from app.models import AdminLoginSession
from sqlalchemy import inspect, text


def test_existing_schema_gains_empty_revocation_table_without_account_changes(installed):
    app, source = installed
    seed(source)
    runner = app.test_cli_runner()
    assert runner.invoke(args=['db', 'upgrade', 'b72e19d4c603']).exit_code == 0
    before = rows(source)
    with app.app_context():
        assert 'admin_login_sessions' not in inspect(db.engine).get_table_names()
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    assert rows(source) == before
    with app.app_context():
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() == 'c83d4e5f9012'
        assert db.session.query(AdminLoginSession).count() == 0
        assert 'ix_admin_login_sessions_expires_at' in {i['name'] for i in inspect(db.engine).get_indexes('admin_login_sessions')}
    assert runner.invoke(args=['db', 'upgrade']).exit_code == 0
    assert rows(source) == before
