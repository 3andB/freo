"""Optional standalone worker: python -m app.production_worker."""
import fcntl
import logging
import time
from app import create_app
from app.extensions import db
from app.services.production_worker import process_one, reconcile, recover, cleanup


def main():
    logging.basicConfig(level=logging.INFO)
    with create_app().app_context():
        from app.services.production_audio import root
        with (root() / '.worker.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            run()


def run():
    recover()
    cleaned = 0
    while True:
        try:
            reconcile()
            if time.monotonic()-cleaned > 3600:
                cleanup();cleaned = time.monotonic()
            if not process_one():
                time.sleep(2)
        except Exception as error:
            db.session.rollback()
            logging.getLogger('freo.production').warning('Production tick failed error_type=%s',type(error).__name__)
            time.sleep(5)


if __name__ == '__main__':
    main()
