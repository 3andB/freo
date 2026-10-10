import json
import pytest
from sqlalchemy import text
from app.extensions import db
from app.models import AuditEvent, InstallationSettings
from app.services.installation_settings import (
    get_setting, import_environment, set_setting, snapshot, SettingsUnavailable,
)
from tests.test_web import app


def test_import_preserves_effective_values_and_reruns_never_overwrite(app, monkeypatch):
    with app.app_context():
        app.config.update(PUBLIC_BASE_URL='https://original.example', FREO_MAX_STATIONS=8)
        monkeypatch.setenv('FREO_LIVE_MIC', '1')
        assert import_environment()
        assert get_setting('FREO_MAX_STATIONS') == 8
        app.config.update(PUBLIC_BASE_URL='https://changed.example', FREO_MAX_STATIONS=3)
        monkeypatch.setenv('FREO_LIVE_MIC', '0')
        assert not import_environment()
        values, revision = snapshot()
        assert revision == 1 and values['PUBLIC_BASE_URL'] == 'https://original.example'
        assert values['FREO_LIVE_MIC'] is True
        assert AuditEvent.query.filter_by(action='settings.import').count() == 1


def test_revision_conflicts_and_invalid_changes_are_atomic(app):
    with app.app_context():
        import_environment()
        assert set_setting('FREO_MAX_STATIONS', 12, 1) == 2
        assert get_setting('FREO_MAX_STATIONS') == 12
        for key, value, revision in [('FREO_MAX_STATIONS', 1, 1),
                                     ('FREO_MAX_STATIONS', True, 2),
                                     ('PUBLIC_BASE_URL', 'https://user:password@example.com', 2),
                                     ('MAX_MEDIA_BATCH_BYTES', 1, 2),
                                     ('DATABASE_URL', 'must-not-persist', 2)]:
            with pytest.raises(ValueError):
                set_setting(key, value, revision)
        assert get_setting('FREO_MAX_STATIONS') == 12
        assert snapshot()[1] == 2
        assert AuditEvent.query.filter_by(action='settings.update').count() == 1


def test_missing_production_settings_fail_closed_without_blocking_bootstrap(app):
    with app.app_context():
        app.config['TESTING'] = False
        with pytest.raises(SettingsUnavailable):
            snapshot()
        assert import_environment()
        assert snapshot()[1] == 1


def test_cli_import_is_idempotent_and_value_is_json(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=['settings', 'import-environment']).exit_code == 0
    result = runner.invoke(args=['settings', 'show'])
    assert json.loads(result.output)['revision'] == 1
    assert runner.invoke(args=['settings', 'set', 'FREO_MAX_STATIONS', '9', '--revision', '1']).exit_code == 0
    assert runner.invoke(args=['settings', 'import-environment']).exit_code == 0
    with app.app_context():
        assert get_setting('FREO_MAX_STATIONS') == 9


def test_ready_rejects_old_schema_and_unadopted_settings(app):
    from app.routes.health import release_schema_head
    app.config['FREO_REQUIRE_SCHEMA_CHECK'] = True
    with app.app_context():
        db.session.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32))'))
        db.session.execute(text("INSERT INTO alembic_version VALUES ('older-version')"))
        db.session.commit()
    assert app.test_client().get('/health').status_code == 200
    assert app.test_client().get('/ready').status_code == 503
    with app.app_context():
        db.session.execute(text('UPDATE alembic_version SET version_num=:head'), {'head': release_schema_head()})
        db.session.commit()
    assert app.test_client().get('/ready').status_code == 503
    with app.app_context():
        import_environment()
    assert app.test_client().get('/ready').status_code == 200


def test_reads_observe_updated_rows_without_worker_restart(app):
    with app.app_context():
        import_environment()
        old = db.session.get(InstallationSettings, 1)
        assert get_setting('FREO_MAX_STATIONS') == 3
        with db.engine.begin() as connection:
            values = dict(old.values, FREO_MAX_STATIONS=17)
            connection.execute(InstallationSettings.__table__.update().values(values=values, revision=2))
        assert get_setting('FREO_MAX_STATIONS') == 17


def test_saved_upload_limits_respect_the_host_request_ceiling(app):
    with app.app_context():
        import_environment()
    app.config['MAX_CONTENT_LENGTH'] = 16
    client = app.test_client()
    client.get('/admin/login')
    response = client.post('/admin/login', data={'csrf': 'x' * 100})
    assert response.status_code == 413


def test_static_asset_urls_change_with_the_release(app):
    from flask import url_for
    from app.version import VERSION
    with app.test_request_context():
        assert url_for('static', filename='player.js').endswith('?v=' + VERSION)
