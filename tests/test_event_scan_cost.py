from datetime import datetime,timedelta,timezone
import uuid
import pytest
from sqlalchemy import event as sql_event
from app.extensions import db
from app.models import Station,Track,TimedEvent,TimedEventOccurrence
from app.automation_worker import EventReader,process_timed_events
from tests.test_web import app

@pytest.mark.parametrize('occurrences',[10,200])
def test_future_recurrence_scan_has_bounded_database_queries(app,monkeypatch,occurrences):
    """A real recurrence horizon must not cost queries proportional to its size."""
    now=datetime.now(timezone.utc)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
        row=TimedEvent(station_id=station.id,uuid=str(uuid.uuid4()),name='Future recurrence',enabled=True,
            revision=1,recurrence_type='HOURLY',content_type='TRACK',track_id=track.id,
            timing_mode='SOFT',local_time=now.time().replace(tzinfo=None),
            early_tolerance_seconds=0,late_tolerance_seconds=30,missed_policy='PLAY_LATE',
            interrupt_policy='NEVER',priority=100,generated_until=now+timedelta(days=30))
        db.session.add(row);db.session.flush()
        for index in range(occurrences):
            at=now+timedelta(hours=index+1)
            db.session.add(TimedEventOccurrence(station_id=station.id,event=row,
                scheduled_for_utc=at,eligible_at_utc=at,deadline_at_utc=at+timedelta(seconds=30),state='PENDING'))
        db.session.commit()
        monkeypatch.setattr('app.services.timed_events.generate_occurrences',lambda *a:None)
        statements=[]
        def collect(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        sql_event.listen(db.engine,'before_cursor_execute',collect)
        try:delay=process_timed_events(station,EventReader(),now)
        finally:sql_event.remove(db.engine,'before_cursor_execute',collect)
        assert delay==3600
        assert len(statements)<35, 'Future-only scan issued '+str(len(statements))+' statements'
        assert TimedEventOccurrence.query.filter_by(state='PENDING').count()==occurrences
        assert all(o.selection_decision_id is None for o in row.occurrences)
