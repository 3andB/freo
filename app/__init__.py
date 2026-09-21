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
from .routes.sound_room import sound_room
from .routes.admin_programming import admin_programming_blueprint
from .routes.admin_imaging import admin_imaging_blueprint
from .routes.admin_live import admin_live_blueprint
from .routes.admin_calendar import admin_calendar
from .routes.admin_events import admin_events_blueprint
from .routes.admin_blocks import admin_blocks_blueprint
from .routes.admin_traffic import admin_traffic_blueprint
from .event_cli import event_cli
from .block_cli import block_cli
from .traffic_cli import traffic_cli


def create_app(config_name=None):
    load_dotenv(os.environ.get("FREO_ENV_FILE", ".env"), override=False)
    name = config_name or os.environ.get("FLASK_ENV", "production")
    configs = {"development": DevelopmentConfig, "production": ProductionConfig, "testing": TestingConfig}
    if name not in configs:
        raise ValueError("FLASK_ENV must be development, production, or testing")
    app = Flask(__name__)
    app.config.from_object(configs[name])
    for key in ("SECRET_KEY", "PUBLIC_BASE_URL", "FREO_DOMAIN", "FREO_INSTALLATION_HOSTS", "FREO_DOMAIN_TARGET_HOST", "FREO_DOMAIN_TARGET_IPS", "FREO_MEDIA_ROOT", "LOG_LEVEL", "FREO_API_URL", "FREO_API_STATE_DIR", "FREO_INSTALL_TYPE", "FREO_GEOIP_DATABASE", "FREO_STATS_STATE_DIR"):
        if key in os.environ:
            app.config[key] = os.environ[key]
    try:
        app.config['FREO_MAX_STATIONS'] = int(os.environ.get('FREO_MAX_STATIONS', app.config['FREO_MAX_STATIONS']))
        if app.config['FREO_MAX_STATIONS'] < 0:
            raise ValueError()
    except ValueError:
        raise RuntimeError('FREO_MAX_STATIONS must be a non-negative integer (0 means unlimited)')
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
    from .routes.license_agreement import license_agreement
    app.register_blueprint(license_agreement)
    from .routes.website import website
    app.register_blueprint(website)
    from .routes.dmca import dmca
    app.register_blueprint(dmca)
    from .routes.central_api import central_api
    app.register_blueprint(central_api, cli_group=None)
    from .routes.statistics import statistics
    app.register_blueprint(statistics, cli_group=None)
    app.register_blueprint(admin_cli, cli_group=None)
    from .routes.catalog_editor import catalog_editor
    app.register_blueprint(catalog_editor)
    from .routes.music_import import music_import
    app.register_blueprint(music_import)
    app.register_blueprint(admin_media_blueprint)
    app.register_blueprint(sound_room)
    from .routes.playlists import playlists
    app.register_blueprint(playlists)
    from .routes.station_settings import station_settings
    from .routes.song_flags import song_flags
    app.register_blueprint(station_settings)
    from .routes.player_experience import player_experience
    app.register_blueprint(player_experience, cli_group=None)
    from .routes.station_domains import station_domains
    from .services.station_domains import route_public_host
    app.register_blueprint(station_domains)
    app.before_request(route_public_host)
    app.register_blueprint(song_flags)
    app.register_blueprint(admin_programming_blueprint)
    app.register_blueprint(admin_imaging_blueprint)
    app.register_blueprint(admin_live_blueprint)
    from .routes.live_mic import live_mic
    app.register_blueprint(live_mic)
    from .routes.schedule_studio import schedule_studio
    app.register_blueprint(schedule_studio)
    app.register_blueprint(admin_calendar)
    app.register_blueprint(admin_events_blueprint)
    app.register_blueprint(admin_blocks_blueprint)
    app.register_blueprint(admin_traffic_blueprint)
    app.register_blueprint(event_cli, cli_group=None)
    app.register_blueprint(block_cli, cli_group=None)
    app.register_blueprint(traffic_cli, cli_group=None)
    from .audio_migration_cli import audio_migration_cli
    app.register_blueprint(audio_migration_cli, cli_group=None)
    try:
        upload_limit = int(os.environ.get('MAX_MEDIA_UPLOAD_BYTES', 128 * 1024 * 1024))
    except ValueError as error:
        raise RuntimeError('MAX_MEDIA_UPLOAD_BYTES must be an integer') from error
    if not 1024 * 1024 <= upload_limit <= 128 * 1024 * 1024:
        raise RuntimeError('MAX_MEDIA_UPLOAD_BYTES must be between 1 MiB and 128 MiB')
    try:
        batch_limit=int(os.environ.get('MAX_MEDIA_BATCH_BYTES',512*1024*1024))
    except ValueError as error:
        raise RuntimeError('MAX_MEDIA_BATCH_BYTES must be an integer') from error
    if batch_limit<upload_limit or batch_limit>1024*1024*1024:
        raise RuntimeError('MAX_MEDIA_BATCH_BYTES must be between the file limit and 1 GiB')
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=name == 'production', PERMANENT_SESSION_LIFETIME=3600,
                      MAX_MEDIA_UPLOAD_BYTES=upload_limit,
                      MAX_MEDIA_BATCH_BYTES=batch_limit,
                      MAX_CONTENT_LENGTH=batch_limit + 1024 * 1024)
    from .services.loudness import gain_for
    app.jinja_env.globals['music_gain'] = gain_for
    return app
