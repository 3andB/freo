class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = None
    SQLALCHEMY_DATABASE_URI = None
    PUBLIC_BASE_URL = ""
    FREO_DOMAIN = ""
    FREO_INSTALLATION_HOSTS = ""
    FREO_DOMAIN_TARGET_HOST = ""
    FREO_DOMAIN_TARGET_IPS = ""
    FREO_MEDIA_ROOT = ""
    LOG_LEVEL = "INFO"
    FREO_MAX_STATIONS = 3
    DMCA_REPORTS_PER_HOUR = 5
    DMCA_TRUSTED_PROXY_IPS = ()


class ProductionConfig(BaseConfig):
    # Bundled Nginx overwrites X-Real-IP and connects over loopback.
    DMCA_TRUSTED_PROXY_IPS = ('127.0.0.1', '::1')
    DEBUG = False

    @staticmethod
    def init_app(app):
        if not app.config["SECRET_KEY"]:
            raise RuntimeError("SECRET_KEY is required in production")
        if not app.config["SQLALCHEMY_DATABASE_URI"]:
            raise RuntimeError("DATABASE_URL is required in production")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
