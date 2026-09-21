"""Restoration must preserve operator documents, including after a failed live run."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.extensions import db
from app.models import Station, ScheduleComposition
from app.services import visual_schedule as vs
from tests.test_web import app
from tests.test_block_scheduling import seed_block

spec=importlib.util.spec_from_file_location('live_stress',Path(__file__).parents[1]/'scripts/stress-live-stations.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def restoration(app,tmp_path):
    runner=module.LiveStress.__new__(module.LiveStress)
    runner.app=app;runner.root=tmp_path;calls=[]
    runner.live=lambda *args,**kwargs:calls.append(('live',args,kwargs))
    runner.switch=lambda *args,**kwargs:calls.append(('switch',args,kwargs))
    runner.event=lambda *args,**kwargs:calls.append(('event',args,kwargs))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        p=vs.policy(station,True);p.mode='SIMPLE';p.activated=True
        block,_=seed_block(station,'Temporary stress block')
        original=dict(mode='SIMPLE',calendar=[],assignments=[],calendar_saved=False,
            activation='original',activated=True,live_simple=None,temporary_block_id=block.id,
            installed_calendar=[{'id':'owned-calendar'}],installed_assignments=[{'id':'owned-assignment'}])
        p.calendar=copy.deepcopy(original['installed_calendar'])
        p.assignments=copy.deepcopy(original['installed_assignments'])
        p.calendar_saved=True;p.activation='test-activation'
        db.session.commit()
    module.write_json(tmp_path/'originals.json',{'test-station':original})
    return runner,calls,original


def test_restore_removes_only_owned_fixtures_and_is_idempotent(restoration):
    runner,calls,original=restoration
    runner.restore()
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        assert p.calendar==[] and p.assignments==[] and not p.calendar_saved
        assert p.activation=='original'
        assert db.session.get(ScheduleComposition,original['temporary_block_id']).archived
    assert json.loads((runner.root/'restoration.json').read_text())['status']=='restored'
    before=len(calls);runner.restore();assert len(calls)==before


@pytest.mark.parametrize('field',['calendar','assignments'])
def test_restore_does_not_overwrite_an_operator_edit(restoration,field):
    runner,calls,original=restoration
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        setattr(p,field,[{'id':'operator-change'}]);db.session.commit()
    with pytest.raises(RuntimeError,match='Restoration needs review'):
        runner.restore()
    assert calls==[]  # No playback change before ownership is checked.
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        assert getattr(p,field)==[{'id':'operator-change'}]
        assert not db.session.get(ScheduleComposition,original['temporary_block_id']).archived


def test_existing_output_cannot_restore_another_active_run(tmp_path):
    runner=module.LiveStress.__new__(module.LiveStress)
    runner.root=tmp_path
    runner.preflight=lambda:None
    runner.restore=lambda:pytest.fail('Must not restore a different run')
    with pytest.raises(RuntimeError,match='new output directory'):
        runner.run()
