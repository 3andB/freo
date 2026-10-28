"""Systemd condition: initialize Flask only when station operations need work.

Keep these predicates aligned with station_lifecycle.process_pending and its
broadcast, stream-audio and directory processors. No application imports here.
"""
from contextlib import closing
import os
import sys

import psycopg2


PENDING_SQL = """SELECT
    EXISTS (SELECT 1 FROM stations WHERE
        lifecycle_state IN ('pending_create', 'pending_delete') OR
        (deleted_at IS NULL AND broadcast_status IN ('pending', 'applying')) OR
        internet_radio_status IN ('pending', 'applying'))
    OR EXISTS (SELECT 1 FROM stream_mounts WHERE audio_status IN ('pending', 'applying'))
"""


def main():
    try:
        url = os.environ['DATABASE_URL']
        if url.startswith('postgresql+psycopg2://'):
            url = 'postgresql://' + url[len('postgresql+psycopg2://'):]
        with closing(psycopg2.connect(url, connect_timeout=3)) as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                cursor.execute('SET LOCAL statement_timeout = 2000')
                cursor.execute(PENDING_SQL)
                # ExecCondition skips the service on 1; 255 reports an error.
                return 0 if cursor.fetchone()[0] else 1
    except Exception:
        # Connection errors can contain credentials. Report no exception text.
        print('Provisioning work check failed; inspect database availability.', file=sys.stderr)
        return 255


if __name__ == '__main__':
    raise SystemExit(main())
