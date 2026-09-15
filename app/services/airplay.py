"""Station-scoped totals from confirmed on-air starts, including existing history."""
from sqlalchemy import func
from app.extensions import db
from app.models import SelectionDecision


def play_counts(station_id, dimension, identifiers=None):
    column = {'track': SelectionDecision.track_id,
              'category': SelectionDecision.category_id}[dimension]
    query = db.session.query(column, func.count(SelectionDecision.id)).filter(
        SelectionDecision.station_id == station_id,
        SelectionDecision.status == 'started',
        SelectionDecision.started_at.isnot(None), column.isnot(None))
    if identifiers is not None:
        query = query.filter(column.in_(identifiers))
    return dict(query.group_by(column).all())
