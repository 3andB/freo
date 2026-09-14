from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/health")
def health():
    return jsonify(status="ok")


@health_blueprint.get("/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        current_app.logger.warning("Database readiness check failed")
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")
