import logging
import os

from dotenv import load_dotenv
from flask import Flask

from .config import DevelopmentConfig, ProductionConfig, TestingConfig
from .extensions import db, migrate
from .routes.health import health_blueprint
from .routes.radio_health import radio_health_blueprint
from .routes.stations import stations_blueprint
from .cli import station_cli
from .media_cli import media_cli
from .routes.media import media_blueprint
from .routes.automation import automation_blueprint
from .automation_cli import automation_cli
from .schedule_cli import schedule_cli
from .routes.schedule import schedule_blueprint
from .routes.web import web_blueprint
from .admin_cli import admin_cli
from .routes.admin_media import admin_media_blueprint


def create_app(config_name=None):
    load_dotenv(os.environ.get("FREO_ENV_FILE", ".env"), override=False)
    name = config_name or os.environ.get("FLASK_ENV", "production")
    configs = {"development": DevelopmentConfig, "production": ProductionConfig, "testing": TestingConfig}
    if name not in configs:
        raise ValueError("FLASK_ENV must be development, production, or testing")
    app = Flask(__name__)
    app.config.from_object(configs[name])
    for key in ("SECRET_KEY", "PUBLIC_BASE_URL", "FREO_DOMAIN", "FREO_MEDIA_ROOT", "LOG_LEVEL"):
        if key in os.environ:
            app.config[key] = os.environ[key]
    if "DATABASE_URL" in os.environ:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
    if hasattr(configs[name], "init_app"):
        configs[name].init_app(app)
    app.logger.setLevel(getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO))
    db.init_app(app)
    from . import models  # noqa: F401 - register migration metadata
    migrate.init_app(app, db)
    app.register_blueprint(health_blueprint)
    app.register_blueprint(radio_health_blueprint)
    app.register_blueprint(stations_blueprint)
    app.register_blueprint(station_cli, cli_group=None)
    app.register_blueprint(media_cli, cli_group=None)
    app.register_blueprint(media_blueprint)
    app.register_blueprint(automation_blueprint)
    app.register_blueprint(automation_cli, cli_group=None)
    app.register_blueprint(schedule_cli, cli_group=None)
    app.register_blueprint(schedule_blueprint)
    app.register_blueprint(web_blueprint)
    app.register_blueprint(admin_cli, cli_group=None)
    app.register_blueprint(admin_media_blueprint)
    try:
        upload_limit = int(os.environ.get('MAX_MEDIA_UPLOAD_BYTES', 128 * 1024 * 1024))
    except ValueError as error:
        raise RuntimeError('MAX_MEDIA_UPLOAD_BYTES must be an integer') from error
    if not 1024 * 1024 <= upload_limit <= 128 * 1024 * 1024:
        raise RuntimeError('MAX_MEDIA_UPLOAD_BYTES must be between 1 MiB and 128 MiB')
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=name == 'production', PERMANENT_SESSION_LIFETIME=3600,
                      MAX_MEDIA_UPLOAD_BYTES=upload_limit,
                      MAX_CONTENT_LENGTH=upload_limit + 1024 * 1024)
    return app
