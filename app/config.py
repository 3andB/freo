class BaseConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = None
    SQLALCHEMY_DATABASE_URI = None
    PUBLIC_BASE_URL = ""
    FREO_DOMAIN = ""
    FREO_MEDIA_ROOT = ""
    LOG_LEVEL = "INFO"


class ProductionConfig(BaseConfig):
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
