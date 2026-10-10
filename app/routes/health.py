from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from functools import lru_cache
from pathlib import Path

from app.extensions import db

health_blueprint = Blueprint("health", __name__)


@lru_cache(maxsize=1)
def release_schema_head():
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(Path(__file__).resolve().parents[2] / 'migrations')).get_current_head()


@health_blueprint.get("/health")
def health():
    return jsonify(status="ok")


@health_blueprint.get("/ready")
def ready():
    from app.services.installation_settings import snapshot, SettingsUnavailable
    try:
        db.session.execute(text("SELECT 1"))
        if not current_app.testing or current_app.config.get('FREO_REQUIRE_SCHEMA_CHECK'):
            revisions = list(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
            if revisions != [release_schema_head()]:
                return jsonify(status='unavailable'), 503
            _, revision = snapshot()
            if not revision:
                return jsonify(status='unavailable'), 503
    except (SQLAlchemyError, SettingsUnavailable, ValueError):
        db.session.rollback()
        current_app.logger.warning("Database readiness check failed")
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")
