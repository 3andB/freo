"""Audit regressions: persistence, recurrence, and bounded handoff recovery."""
import json
import random
from datetime import date, timedelta
import pytest
from app.extensions import db
from app.models import ScheduleComposition, ScheduleCompositionRevision, ScheduleTransition, SelectionDecision
from app.services import visual_schedule as vs
from app.services.schedule_conflicts import first_common_day
from tests.test_web import app, admin_client
from tests.test_visual_schedule import setup, at


def test_distant_overlap_rejected_and_following_retains_phase(app):
    with app.app_context():
        s,p,ref=setup()
        rows=[dict(id='daily',start=0,end=3600,source=ref,rule=dict(frequency='daily',anchor='2026-01-01',interval=365)),dict(id='monthly',start=0,end=3600,source=ref,rule=dict(frequency='monthly',anchor='2026-01-01',month_day=31))]
        with pytest.raises(ValueError,match='2028-12-31'):vs.clean_document(s,rows)
        rule=vs.clean_rule(dict(frequency='daily',anchor='2026-09-01',starts_on='2026-09-06',interval=3))
        assert not vs.matches(rule,date(2026,9,4))
        assert not vs.matches(rule,date(2026,9,6))
        assert vs.matches(rule,date(2026,9,7))
        # Selected dates far outside an anchor's first year must also be checked.
        rows=[dict(id=str(i),start=0,end=3600,source=ref,rule=dict(frequency='dates',anchor='2020-01-01',dates=['2040-02-29'])) for i in range(2)]
        with pytest.raises(ValueError,match='2040-02-29'):vs.clean_document(s,rows)


def test_conflict_solver_matches_independent_day_scan():
    rng=random.Random(170926)
    start=date(2026,1,1)
    def rule():
        anchor=start+timedelta(days=rng.randrange(60))
        return vs.clean_rule(dict(frequency=rng.choice(['once','dates','daily','weekly','monthly']),anchor=anchor.isoformat(),until='2028-12-31',interval=rng.randrange(1,8),
            weekdays=rng.sample(range(7),rng.randrange(1,8)),month_day=rng.randrange(1,32),nth=rng.choice([0,1,2,3,4,5,-1]),weekday=rng.randrange(7),
            dates=[(start+timedelta(days=rng.randrange(1000))).isoformat() for _ in range(5)],exceptions=[(start+timedelta(days=rng.randrange(1000))).isoformat() for _ in range(5)]))
    for _ in range(250):
        a,b=rule(),rule();offset=rng.choice([-1,0,1])
        expected=next((day.toordinal() for i in range(1096) if vs.matches(a,day:=start+timedelta(days=i)) and vs.matches(b,day+timedelta(days=offset))),None)
        assert first_common_day(a,b,offset,vs.matches)==expected,(a,b,offset)


def test_block_save_is_atomic_on_assignment_error_and_stale_revision(app):
    client=admin_client(app);url='/admin/stations/test-station/schedule-studio/api/block-workspace'
    def post(data):return client.post(url,data={'csrf':'test-admin-csrf-token','payload':json.dumps(data)})
    with app.app_context():
        s,p,ref=setup();revision=p.revision
        comp=dict(kind='BLOCK',name='Atomic',sections=[dict(id='song',start=0,end=86400,source=ref)])
    assert post(dict(composition=comp,items=[{}],revision=revision)).status_code==400
    with app.app_context():assert ScheduleComposition.query.count()==0 and ScheduleCompositionRevision.query.count()==0
    response=post(dict(composition=comp,items=[],revision=revision));assert response.status_code==200
    saved=response.json['composition'];saved['name']='Must not persist'
    assert post(dict(composition=saved,items=[],revision=revision)).status_code==400
    with app.app_context():assert ScheduleComposition.query.one().name=='Atomic' and ScheduleComposition.query.one().revision==1


@pytest.mark.parametrize('phase',['PENDING','PREPARING','FADING'])
@pytest.mark.parametrize('response',['offline','FADING','APPLIED'])
def test_handoff_deadlines_release_editor_without_false_success(app,monkeypatch,phase,response):
    from app.services import schedule_switch as switch
    from app.automation_worker import EventReader
    from datetime import datetime,timezone
    with app.app_context():
        s,p,ref=setup();s.automation.hold=False
        command=ScheduleTransition(id='11111111-1111-4111-8111-111111111111',station_id=s.id,mode='SIMPLE',previous_mode='CALENDAR',revision=p.revision,state=phase,created_at=datetime.now(timezone.utc)-timedelta(seconds=180))
        if phase!='PENDING':
            decision=SelectionDecision(station_id=s.id,track_id=ref['id'],status='queued',liquidsoap_request_id=99,socket_identity='test')
            db.session.add(decision);db.session.flush();command.decision_id=decision.id
        db.session.add(command);db.session.commit()
        monkeypatch.setattr(EventReader,'collect',lambda *a:0)
        monkeypatch.setattr(switch,'socket_identity',lambda *a:'test')
        monkeypatch.setattr(switch,'queued_ids',lambda *a:set())
        def socket(*args):
            if response=='offline':raise OSError('unavailable')
            return response
        monkeypatch.setattr(switch,'_command',socket)
        assert not switch.process_transition(s,EventReader())
        assert command.state=='FAILED' and p.mode=='CALENDAR'
        assert s.automation.hold==(phase!='PENDING')
        if phase!='PENDING':assert command.decision.status=='queued' and command.decision.started_at is None


def test_event_preview_includes_last_hour_of_fall_back_day(app):
    from app.models import Station,Track
    from app.services.timed_events import save_event
    client=admin_client(app)
    with app.app_context():
        s=Station.query.filter_by(slug='test-station').one();s.timezone='America/New_York';db.session.commit()
        save_event(s.slug,name='Late Sunday',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=Track.query.first().uuid,local_date='2026-11-01',local_time='23:30')
    result=client.get('/admin/stations/test-station/schedule-studio/api/events?date=2026-11-01&days=1')
    assert result.status_code==200 and result.json['items'][0]['name']=='Late Sunday'


def test_expired_handoff_reconciles_only_matching_observed_engine_token(app,monkeypatch):
    from app.services import schedule_switch as switch
    from app.automation_worker import EventReader
    from datetime import datetime,timezone
    with app.app_context():
        s,p,ref=setup();s.automation.hold=True
        decision=SelectionDecision(station_id=s.id,track_id=ref['id'],status='started',started_at=datetime.now(timezone.utc),liquidsoap_request_id=99,socket_identity='test')
        db.session.add(decision);db.session.flush()
        command=ScheduleTransition(id='22222222-2222-4222-8222-222222222222',station_id=s.id,mode='SIMPLE',simple=ref,previous_mode='CALENDAR',revision=p.revision,state='FADING',created_at=datetime.now(timezone.utc)-timedelta(seconds=180),decision_id=decision.id)
        db.session.add(command);db.session.commit()
        monkeypatch.setattr(EventReader,'collect',lambda *a:0)
        monkeypatch.setattr(switch,'socket_identity',lambda *a:'test')
        commands=[]
        def socket(slug,value):commands.append(value);return 'APPLIED|'+command.id
        monkeypatch.setattr(switch,'_command',socket)
        assert switch.process_transition(s,EventReader())
        assert commands==['freo_schedule.status'] and p.mode=='SIMPLE'
        assert command.state=='APPLIED' and not s.automation.hold


def test_overnight_overlap_sweep_matches_day_expansion():
    from app.services.schedule_conflicts import validate_overlaps
    rng=random.Random(9442);start=date(2026,1,1)
    for _ in range(200):
        rows=[]
        for i in range(3):
            begin=rng.randrange(24)*3600
            rule=vs.clean_rule(dict(frequency='weekly',anchor='2026-01-01',until='2026-02-28',weekdays=rng.sample(range(7),2),interval=rng.randrange(1,4)))
            rows.append(dict(id=str(i),start=begin,end=begin+rng.randrange(1,25)*3600,rule=rule))
        collision=False
        for delta in range(61):
            entries=vs.day_entries(rows,start+timedelta(days=delta))
            if any(a['end']>b['start'] for a,b in zip(entries,entries[1:])):collision=True;break
        try:validate_overlaps(rows,vs.matches)
        except ValueError:assert collision,rows
        else:assert not collision,rows
