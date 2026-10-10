"""Document-scoped saves survive mode/settings changes without lost edits."""
import copy
import json
import uuid
import pytest
from app.extensions import db
from app.models import ChannelSchedule, Station, Track, ScheduleTransition
from app.services import visual_schedule as vs
from app.services.schedule_documents import merge_items, ScheduleConflict
from tests.test_web import app, admin_client

BASE='/admin/stations/test-station/schedule-studio/api/'


def post(client, action, **data):
    return client.post(BASE+action,data={'csrf':'test-admin-csrf-token','payload':json.dumps(data)})


def seed(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        row=vs.policy(station,True)
        source=vs.source(station,dict(kind='song',id=Track.query.first().id))
        rows=[dict(id=name,start=start,end=start+3600,source=source,rule=dict(frequency='once',anchor='2026-09-21')) for name,start in [('a',3600),('b',10800)]]
        row.calendar=vs.clean_document(station,rows);row.calendar_saved=True;db.session.commit()
        return copy.deepcopy(row.calendar),row.revision,source


def test_simple_save_after_mode_revision_and_calendar_edit(app):
    rows,revision,source=seed(app);client=admin_client(app)
    with app.app_context():
        row=ChannelSchedule.query.first();row.mode='SIMPLE';row.activated=True;row.revision+=1;db.session.commit()
    response=post(client,'simple',revision=revision,base=None,source=source)
    assert response.status_code==200 and response.json['source']==source
    newer=copy.deepcopy(rows);newer[0]['end']+=60
    assert post(client,'calendar',revision=revision,base=rows,items=newer).status_code==200
    # A retried save is idempotent and does not falsely conflict with its own success.
    assert post(client,'simple',revision=revision,base=None,source=source).status_code==200
    with app.app_context():
        row=ChannelSchedule.query.first();assert row.simple==source and row.calendar[0]['end']==7260


def test_calendar_combines_independent_edits_and_rejects_same_item_conflict(app):
    rows,revision,source=seed(app);client=admin_client(app)
    first=copy.deepcopy(rows);first[0]['start']=1800
    assert post(client,'calendar',revision=revision,base=rows,items=first).status_code==200
    second=copy.deepcopy(rows);second[1]['end']=15000
    response=post(client,'calendar',revision=revision,base=rows,items=second)
    assert response.status_code==200
    assert [(r['start'],r['end']) for r in response.json['items']]==[(1800,7200),(10800,15000)]
    conflict=copy.deepcopy(rows);conflict[0]['start']=0;conflict[1]['start']=9000
    response=post(client,'calendar',revision=revision,base=rows,items=conflict)
    assert response.status_code==409 and response.json['conflict']
    assert response.json['state']['calendar'][1]['start']==10800
    with app.app_context():assert ChannelSchedule.query.first().calendar[0]['start']==1800
    # Old clients retain revision protection.
    assert post(client,'calendar',revision=revision,items=rows).status_code==400


def test_calendar_save_defers_during_handoff_then_accepts_new_revision(app):
    rows,revision,source=seed(app);client=admin_client(app)
    with app.app_context():
        db.session.add(ScheduleTransition(id=str(uuid.uuid4()),station_id=1,mode='SIMPLE',previous_mode='CALENDAR',revision=revision,state='PENDING'))
        db.session.commit()
    changed=copy.deepcopy(rows);changed[0]['start']=1800
    response=post(client,'calendar',revision=revision,base=rows,items=changed)
    assert response.status_code==409 and response.json['retryable']
    with app.app_context():
        assert ChannelSchedule.query.first().calendar==rows
        ScheduleTransition.query.first().state='APPLIED';row=ChannelSchedule.query.first();row.revision+=1;row.mode='SIMPLE';db.session.commit()
    assert post(client,'calendar',revision=revision,base=rows,items=changed).status_code==200


def test_merged_calendar_still_checks_overlap_and_source_access(app):
    rows,revision,source=seed(app);client=admin_client(app)
    first=copy.deepcopy(rows);first[0]['end']=10000
    assert post(client,'calendar',revision=revision,base=rows,items=first).status_code==200
    second=copy.deepcopy(rows);second[1]['start']=9000
    response=post(client,'calendar',revision=revision,base=rows,items=second)
    assert response.status_code==400 and 'overlap' in response.json['error']
    invalid=copy.deepcopy(rows);invalid[1]['source']={'kind':'song','id':99999}
    assert post(client,'calendar',revision=revision,base=rows,items=invalid).status_code==400
    with app.app_context():assert ChannelSchedule.query.first().calendar==vs.clean_document(Station.query.first(),first)


def test_default_playlist_save_is_independent_of_calendar_revision(app):
    from app.models import Playlist, PlaylistItem
    rows,revision,source=seed(app);client=admin_client(app)
    with app.app_context():
        playlist=Playlist(station_id=1,name='Default choice');playlist.items.append(PlaylistItem(track_id=source['id'],position=1))
        db.session.add(playlist);db.session.commit();identifier=playlist.id
    changed=copy.deepcopy(rows);changed[0]['start']=1800
    assert post(client,'calendar',revision=revision,base=rows,items=changed).status_code==200
    response=post(client,'default',revision=revision,base=None,playlist=identifier)
    assert response.status_code==200 and response.json['name']=='Default choice'
    with app.app_context():assert ChannelSchedule.query.first().default_playlist_id==identifier


def test_merge_deletion_retry_and_conflict():
    base=[dict(id='a',start=1),dict(id='b',start=2)]
    remote=base+[dict(id='c',start=3)]
    assert merge_items(base,base[1:],remote)==remote[1:]
    assert merge_items(base,base[1:],remote[1:])==remote[1:]
    with pytest.raises(ScheduleConflict):merge_items(base,base[1:],[dict(id='a',start=4),base[1]])
    assert base[0]['start']==1
