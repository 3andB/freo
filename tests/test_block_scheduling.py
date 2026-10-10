"""Saved Block lifecycle, calendar composition, and effective playback diagnostics."""
import copy
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from app.extensions import db
from app.models import Station, Track, Playlist, PlaylistItem, ScheduleComposition, ChannelSchedule
from app.services import visual_schedule as vs
from app.services.media_storage import LocalMediaStorage
from tests.test_web import app, admin_client
from tests.test_schedule_autosave import post


def seed_block(station, name='Chill Night', start=0, end=86400):
    song = Track.query.first()
    playlist = Playlist(station_id=station.id, name=name+' music', mode='STRAIGHT')
    playlist.items.append(PlaylistItem(track_id=song.id, position=1))
    db.session.add(playlist); db.session.flush()
    block = vs.save_composition(station, dict(kind='BLOCK', name=name, description='', sections=[
        dict(id=str(uuid.uuid4()), start=start, end=end, source=dict(kind='playlist', id=playlist.id))]))
    db.session.flush()
    return block, playlist


def occurrence(block, day, **times):
    return dict(id=str(uuid.uuid4()), start=times.get('start',0), end=times.get('end',86400),
                source=dict(kind='block',id=block.id,version=block.revision),
                rule=dict(frequency='once',anchor=day))


def test_saved_unassigned_block_reports_exact_remedy_and_assignment_does_not_version(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.timezone='America/Denver'
        policy=vs.policy(station,True);policy.mode='SIMPLE';policy.activated=True
        block,playlist=seed_block(station);db.session.commit()
        saved=vs.composition_json(block);revision=policy.revision
        today=datetime.now(ZoneInfo(station.timezone)).date().isoformat()
    preview=post(client,'transition-preview',mode='BLOCKS').json
    assert preview['code']=='unassigned' and not preview['playable']
    assert 'No Block is assigned to today' in preview['message']
    response=post(client,'transition',id=str(uuid.uuid4()),mode='BLOCKS',current='SIMPLE',revision=revision)
    assert response.status_code==400 and 'assigned to today' in response.json['error']
    assignment=dict(id=str(uuid.uuid4()),rule=dict(frequency='once',anchor=today),pattern=[dict(kind='block',id=saved['id'],version=1)])
    response=post(client,'block-workspace',composition=saved,base=[],items=[assignment],revision=revision)
    assert response.status_code==200,response.json
    assert response.json['composition']['revision']==1
    preview=post(client,'transition-preview',mode='BLOCKS').json
    assert preview['playable'] and not preview['using_default'] and preview['program']=='Chill Night'
    with app.app_context():
        assert ChannelSchedule.query.first().mode=='SIMPLE'
        assert len(db.session.get(ScheduleComposition,saved['id']).versions)==1


def test_three_calendar_blocks_resolve_at_boundaries_and_preserve_versions(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *args:True)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        policy.activated=True;policy.mode='CALENDAR'
        blocks=[seed_block(station,name)[0] for name in ('Chill Night','Bright Day','Weekend')]
        days=['2026-09-21','2026-09-22','2026-09-23']
        policy.calendar=vs.clean_document(station,[occurrence(block,day) for block,day in zip(blocks,days)])
        policy.calendar_saved=True;db.session.commit()
        keys=[]
        for block,day in zip(blocks,days):
            at=datetime.fromisoformat(day+'T00:00:00+00:00')
            resolved=vs.resolve_visual(station,at);keys.append(resolved['key'])
            assert resolved['label']==block.name and resolved['source']['kind']=='playlist'
            decision=vs.select_visual(station,resolved,LocalMediaStorage(),at)
            assert decision.track_id==Track.query.first().id
            assert decision.schedule_occurrence==resolved['key']
            assert vs.resolve_visual(station,at.replace(hour=23,minute=59,second=59))['label']==block.name
        assert len(set(keys))==3
        # Editing the library cannot rewrite the version already scheduled.
        old=copy.deepcopy(policy.calendar)
        data=vs.composition_json(blocks[0]);data['sections']=[]
        vs.save_composition(station,data);db.session.commit()
        assert policy.calendar==old
        assert vs.resolve_visual(station,datetime(2026,9,21,12,tzinfo=timezone.utc))['source'] is not None
        db.session.remove()  # Playback can resolve saved references after a worker restart.
        station=Station.query.filter_by(slug='test-station').one()
        assert vs.resolve_visual(station,datetime(2026,9,22,12,tzinfo=timezone.utc))['label']=='Bright Day'


def test_calendar_block_api_validates_station_revision_and_overlaps(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        block,_=seed_block(station);row=occurrence(block,'2026-09-21');db.session.commit();revision=policy.revision
    assert post(client,'calendar',revision=revision,base=[],items=[row]).status_code==200
    conflicting=dict(copy.deepcopy(row),id=str(uuid.uuid4()))
    assert post(client,'calendar-preview',items=[row,conflicting]).status_code==400
    bad=copy.deepcopy(row);bad['source']['version']=999
    assert post(client,'calendar-preview',items=[bad]).status_code==400
    with app.app_context():
        other=Station.query.filter_by(slug='second-station').one()
        with pytest.raises(ValueError):vs.clean_document(other,[row])
        with pytest.raises(ValueError):vs.save_composition(station,dict(kind='BLOCK',name='Recursive',sections=[dict(start=0,end=86400,source=row['source'])]))


@pytest.mark.parametrize('scenario,code', [('gap','gap'),('disabled','unplayable'),('missing','unassigned')])
def test_preview_distinguishes_empty_sections_unplayable_songs_and_fallback(app,scenario,code):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        block,playlist=seed_block(station)
        if scenario=='gap':
            data=vs.composition_json(block);data['sections']=[];vs.save_composition(station,data)
        today=datetime.now(timezone.utc).date().isoformat()
        if scenario!='missing':
            policy.assignments=vs.clean_document(station,[dict(id=str(uuid.uuid4()),rule=dict(frequency='once',anchor=today),pattern=[dict(kind='block',id=block.id,version=block.revision)])],assignments=True)
        if scenario=='disabled':Track.query.first().enabled=False
        db.session.commit()
        preview=vs.transition_preview(station,'BLOCKS')
        assert not preview['playable'] and preview['code']==code
        if scenario!='disabled':
            policy.default_playlist_id=playlist.id;db.session.commit()
            preview=vs.transition_preview(station,'BLOCKS')
            assert preview['playable'] and preview['using_default'] and preview['code']==code


def test_calendar_block_playlist_cursor_survives_new_worker_session(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *args:True)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        policy.activated=True;policy.mode='CALENDAR'
        block,playlist=seed_block(station)
        first_id=Track.query.first().id
        second=Track(station_id=station.id,uuid=str(uuid.uuid4()),title='Second song',artist='Test',
            original_filename='second.mp3',storage_key='b'*32+'.mp3',media_type='mp3',duration_ms=20000,
            sample_rate_hz=44100,channels=2,file_size_bytes=1000,checksum_sha256='b'*64,enabled=True,ingest_status='accepted')
        db.session.add(second);db.session.flush();second_id=second.id
        playlist.items.append(PlaylistItem(track_id=second.id,position=2))
        policy.calendar=vs.clean_document(station,[occurrence(block,'2026-09-21')]);db.session.commit()
        at=datetime(2026,9,21,12,tzinfo=timezone.utc)
        selected=vs.select_visual(station,vs.resolve_visual(station,at),LocalMediaStorage(),at)
        assert selected.track_id==first_id;db.session.commit();db.session.remove()
        station=Station.query.filter_by(slug='test-station').one()
        selected=vs.select_visual(station,vs.resolve_visual(station,at),LocalMediaStorage(),at)
        assert selected.track_id==second_id
        assert vs.select_visual(station,vs.resolve_visual(station,at),LocalMediaStorage(),at).track_id==first_id


@pytest.mark.parametrize('day,instants',[('2026-03-08',['2026-03-08T08:30:00+00:00','2026-03-08T09:30:00+00:00']),('2026-11-01',['2026-11-01T07:30:00+00:00','2026-11-01T08:30:00+00:00'])])
def test_calendar_block_covers_station_day_across_dst(app,day,instants):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.timezone='America/Denver'
        policy=vs.policy(station,True);policy.activated=True;policy.mode='CALENDAR'
        block,_=seed_block(station);policy.calendar=vs.clean_document(station,[occurrence(block,day)]);db.session.commit()
        resolved=[vs.resolve_visual(station,datetime.fromisoformat(instant)) for instant in instants]
        assert all(item['label']=='Chill Night' and item['reason'] is None for item in resolved)
        assert resolved[0]['key']==resolved[1]['key']


def test_show_inside_calendar_block_repeats_and_versions_remain_pinned(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        policy.activated=True;policy.mode='CALENDAR'
        show=vs.save_composition(station,dict(kind='SHOW',name='Hourly show',duration=3600,sections=[dict(id='music',start=0,end=3600,source=dict(kind='song',id=Track.query.first().id))]));db.session.flush()
        block=vs.save_composition(station,dict(kind='BLOCK',name='Show day',sections=[dict(id='shows',start=0,end=86400,source=dict(kind='show',id=show.id))]));db.session.flush()
        policy.calendar=vs.clean_document(station,[occurrence(block,'2026-09-21')]);db.session.commit()
        first=vs.resolve_visual(station,datetime(2026,9,21,0,tzinfo=timezone.utc))
        second=vs.resolve_visual(station,datetime(2026,9,21,1,tzinfo=timezone.utc))
        assert first['source']['kind']==second['source']['kind']=='song'
        assert first['key']!=second['key']
        data=vs.composition_json(show);data['sections']=[];vs.save_composition(station,data);db.session.commit()
        assert vs.resolve_visual(station,datetime(2026,9,21,1,tzinfo=timezone.utc))['key']==second['key']


def test_simple_preview_starts_new_show_at_beginning(app):
    from datetime import timedelta
    from app.models import ScheduleTransition
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        old=ScheduleTransition(id=str(uuid.uuid4()),station_id=station.id,mode='SIMPLE',previous_mode='CALENDAR',revision=1,state='APPLIED',completed_at=datetime.now(timezone.utc)-timedelta(minutes=30))
        db.session.add(old);policy.activation=old.id;policy.mode='SIMPLE';policy.activated=True
        show=vs.save_composition(station,dict(kind='SHOW',name='Intro',duration=3600,sections=[dict(id='first',start=0,end=900,source=dict(kind='song',id=Track.query.first().id))]));db.session.flush()
        source=vs.source(station,dict(kind='show',id=show.id));db.session.commit()
        preview=vs.transition_preview(station,'SIMPLE',simple=source)
        assert preview['playable'] and preview['reason'] is None


def test_preview_accepts_older_source_references_without_display_name(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        policy.simple=dict(kind='song',id=Track.query.first().id);db.session.commit()
    result=post(client,'transition-preview',mode='SIMPLE')
    assert result.status_code==200,result.json
    assert result.json['playable'] and 'Verified Test Track' in result.json['message']
