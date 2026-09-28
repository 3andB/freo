"""Offline dependency smoke check. Never reads installation secrets or connects to DBs."""
import argparse
import json
import os
from importlib.metadata import version


def check(*, live_mic=False):
    import psycopg
    import psycopg2
    from sqlalchemy import create_engine
    from packaging.version import Version

    if not Version('0.3.2-rc.2') < Version('0.3.2'):
        raise RuntimeError('Upgrade version comparison failed')

    if psycopg.pq.__impl__ != 'binary':
        raise RuntimeError('Freo requires the psycopg[binary] distribution')
    drivers = {}
    for scheme in ('postgresql', 'postgresql+psycopg', 'postgresql+psycopg2'):
        engine = create_engine(f'{scheme}://dependency_check@127.0.0.1/unused')
        drivers[scheme] = engine.dialect.driver
        engine.dispose()  # Engine creation loads the DBAPI but opens no connection.

    # Check the same factory/CLI registration that failed during installation.
    # Run this module in its own process: these synthetic values are intentional.
    os.environ.update(FREO_ENV_FILE=os.devnull, FLASK_ENV='production',
                      SECRET_KEY='dependency-check-only',
                      DATABASE_URL='postgresql+psycopg://dependency_check@127.0.0.1/unused')
    from app import create_app
    from app.extensions import db
    app = create_app()
    result = app.test_cli_runner().invoke(args=['db', '--help'])
    if result.exit_code:
        raise RuntimeError('Flask migration command failed to load') from result.exception
    with app.app_context():
        db.engine.dispose()
    packages = ['SQLAlchemy', 'psycopg', 'psycopg-binary', 'psycopg2-binary', 'packaging']
    if live_mic:
        import aiortc  # noqa: F401
        import aiohttp  # noqa: F401
        packages += ['aiortc', 'aiohttp']
    return dict(drivers=drivers, migration_cli='passed',
                packages={name: version(name) for name in packages})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-mic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(live_mic=args.live_mic), sort_keys=True))
