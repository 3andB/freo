"""Durable manual requests; web processes never touch reporter state or credentials."""
import time
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import CentralConnectionCheck

COOLDOWN = 60


def queue_check(now=None):
    now = time.time() if now is None else now
    values = dict(request_id=str(uuid4()), status='queued', requested_at=now,
                  started_at=None, finished_at=None, result={})
    row = db.session.get(CentralConnectionCheck, 1)
    if row is None:
        db.session.add(CentralConnectionCheck(id=1, **values))
        try:
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()  # Another administrator queued the singleton first.
        row = db.session.get(CentralConnectionCheck, 1)
    if row.status in ('queued', 'checking') or now < next_allowed(row):
        return False
    changed = CentralConnectionCheck.query.filter_by(id=1, request_id=row.request_id,
        status=row.status).update(values, synchronize_session=False)
    db.session.commit()
    return bool(changed)


def next_allowed(row):
    return max(row.requested_at + COOLDOWN, row.result.get('retry_at', 0))


def check_status(now=None):
    now = time.time() if now is None else now
    row = db.session.get(CentralConnectionCheck, 1)
    if row is None:
        return dict(request_id=None, status='idle', message='', busy=False, retry_at=0)
    busy = row.status in ('queued', 'checking')
    message = row.result.get('message', '')
    if row.status == 'queued':
        message = ('Waiting for the background reporter. The check will run when it is available.'
                   if now - row.requested_at > 120 else 'Queued — waiting for the reporter.')
    elif row.status == 'checking':
        message = 'Checking connection…'
    return dict(request_id=row.request_id, status=row.status, message=message, busy=busy,
                retry_at=next_allowed(row), finished_at=row.finished_at)
