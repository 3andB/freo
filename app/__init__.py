import logging
import os

from dotenv import load_dotenv
from flask import Flask

from .config import DevelopmentConfig, ProductionConfig, TestingConfig
from .extensions import db, migrate
from .routes.health import health_blueprint
from .routes.radio_health import radio_health_blueprint


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
    migrate.init_app(app, db)
    app.register_blueprint(health_blueprint)
    app.register_blueprint(radio_health_blueprint)
    return app
