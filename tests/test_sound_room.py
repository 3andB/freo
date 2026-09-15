"""Sound Room mutations, offline processing, and permanent deletion boundaries."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import pytest
from app.extensions import db
from app.models import Station, Track, MediaCategory, MusicTag, MediaIngestJob, SelectionDecision
from app.services.loudness import gain_for
from tests.test_web import app as app_fixture, admin_client


@pytest.fixture
def app(app_fixture):return app_fixture


def action(client,kind,data,slug='test-station'):
    return client.post(f'/admin/api/stations/{slug}/music/actions/{kind}',data={'csrf':'test-admin-csrf-token','data':json.dumps(data)})


def test_sound_room_category_tag_notes_and_undo(app):
    client=admin_client(app)
    assert client.get('/admin/stations/test-station/sound-room').status_code==200
    assert client.get('/admin/stations/test-station/media').status_code==200
    catalog=client.get('/admin/api/stations/test-station/music').json
    song=catalog['songs'][0];category=catalog['categories'][0]
    assert action(client,'create-tag',{'name':'HOT','color':'#e19c71'}).status_code==200
    tag=client.get('/admin/api/stations/test-station/music').json['tags'][0]
    result=action(client,'assign',{'songs':[song['uuid']],'kind':'tag','target':tag['id'],'operation':'add'})
    assert result.status_code==200 and result.json['undo']
    undo=result.json['undo']
    # A duplicate add has no inverse removal; Undo only touches actual changes.
    assert action(client,'assign',{'songs':[song['uuid']],'kind':'tag','target':tag['id'],'operation':'add'}).json['undo'] is None
    assert action(client,'undo',{'id':undo}).status_code==200
    assert action(client,'undo',{'id':undo}).status_code==409
    assert not client.get('/admin/api/stations/test-station/music/'+song['uuid']).json['tags']
    assert action(client,'notes',{'songs':[song['uuid']],'notes':'Great opener','previous':''}).status_code==200
    assert action(client,'notes',{'songs':[song['uuid']],'notes':'Stale','previous':''}).status_code==409
    assert action(client,'edit-category',{'id':category['id'],'name':'Evening','description':'Warm songs','enabled':False}).status_code==200
    assert client.get('/admin/api/stations/test-station/music?category='+str(category['id'])).json['total']==1
    assert action(client,'assign',{'songs':[song['uuid']],'kind':'category','target':category['id'],'operation':'remove'}).status_code==200
    assert client.get('/admin/api/stations/test-station/music?category='+str(category['id'])).json['total']==0
    assert action(client,'assign',{'songs':[song['uuid']],'kind':'category','target':category['id'],'operation':'add'}).status_code==200


def test_sound_room_validation_and_station_isolation(app):
    client=admin_client(app)
    assert app.test_client().get('/admin/api/stations/test-station/music').status_code==302
    assert client.post('/admin/api/stations/test-station/music/actions/create-tag',data={'data':'{}'}).status_code==400
    catalog=client.get('/admin/api/stations/test-station/music').json;song=catalog['songs'][0]
    category=catalog['categories'][0]
    assert action(client,'assign',{'songs':[song['uuid']],'kind':'category','target':category['id'],'operation':'add'},'second-station').status_code==409
    assert action(client,'notes',{'songs':[song['uuid'],'foreign'],'notes':'bad'}).status_code==409
    assert action(client,'create-tag',{'name':'HOT','color':'url(evil)'}).status_code==409
    assert action(client,'create-tag',{'name':'HOT','color':'#b9e79b'}).status_code==200
    assert action(client,'create-tag',{'name':'hot','color':'#b9e79b'}).status_code==409
    assert action(client,'loudness',{'target':-16}).status_code==200
    assert action(client,'loudness',{'target':'nan'}).status_code==409


def test_gain_policy_handles_boost_attenuation_peaks_and_missing_analysis(app):
    with app.app_context():
        song=Track.query.first();song.analysis_status='complete';song.loudness_lufs=-20;song.true_peak_db=-8
        assert gain_for(song)['db']==4
        song.loudness_lufs=-10;assert gain_for(song)['db']==-6
        song.loudness_lufs=-25;song.true_peak_db=-2
        assert gain_for(song)['db']==.5 and gain_for(song)['status']=='Peak limited'
        song.loudness_lufs=float('nan');assert gain_for(song)['factor']==1
        song.analysis_status='pending';assert gain_for(song)['status']=='Needs analysis'


def test_real_audio_analysis_idle_queue_preserves_notes_and_cues(app,tmp_path,monkeypatch):
    audio=tmp_path/'test.mp3'
    subprocess.run(['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=440:duration=2','-codec:a','libmp3lame',str(audio)],check=True)
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:audio)
    monkeypatch.setattr('app.services.analysis_queue.extract_artwork',lambda song:None)
    from app.services.analysis_queue import process_analysis,request_analysis
    with app.app_context():
        song=Track.query.first();song.notes='Keep this';song.cue_in_ms=123;song.cue_out_ms=1800;db.session.commit()
        assert process_analysis()
        assert song.analysis_status=='complete' and song.loudness_lufs is not None and song.true_peak_db is not None
        assert song.notes=='Keep this' and song.cue_in_ms==123 and song.cue_out_ms==1800
        assert not process_analysis()
        assert request_analysis(song);db.session.commit()
        assert not process_analysis()
        assert process_analysis(requested=True)


def test_analysis_failure_is_retried_with_backoff(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:(_ for _ in ()).throw(FileNotFoundError()))
    from app.services.analysis_queue import process_analysis
    with app.app_context():
        assert process_analysis()
        song=Track.query.first();assert song.analysis_status=='failed' and song.analysis_attempts==1
        assert not process_analysis()
        assert song.enabled


def test_permanent_delete_removes_audio_retains_history_and_requires_confirmation(app,tmp_path,monkeypatch):
    media=tmp_path/'media';originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    key='a'*32+'.mp3';audio=originals/key;audio.write_bytes(b'private audio')
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    with app.app_context():
        song=Track.query.first();identifier=song.uuid;song.storage_key=key;song.station.desired_state='stopped';db.session.commit()
    client=admin_client(app)
    assert action(client,'delete',{'songs':[identifier]}).status_code==409
    result=action(client,'delete',{'songs':[identifier],'confirm':identifier});assert result.status_code==200
    assert audio.exists()
    from app.ingest_worker import process_one
    with app.app_context():
        assert process_one();song=Track.query.filter_by(uuid=identifier).one()
        assert song.deleted_at and not audio.exists()
        assert SelectionDecision.query.filter_by(track_id=song.id).count()==1
        assert MediaIngestJob.query.filter_by(kind='delete').one().status=='accepted'
    assert client.get('/admin/api/stations/test-station/music').json['total']==0
    assert client.get('/admin/stations/test-station/media/'+identifier).status_code==404
    assert client.get('/admin/stations/test-station/media/'+identifier+'/audition').status_code==404


def test_delete_blocks_pending_playback_and_allows_detail_form(app):
    with app.app_context():
        song=Track.query.first();song.station.desired_state='stopped';identifier=song.uuid
        SelectionDecision.query.first().status='queued';db.session.commit()
    client=admin_client(app)
    assert action(client,'delete',{'songs':[identifier],'confirm':identifier}).status_code==409
    page=client.get('/admin/stations/test-station/media/'+identifier)
    assert b'Permanently delete song' in page.data and b'data-preview=' in page.data
    assert client.post('/admin/stations/test-station/media/'+identifier+'/delete',data={'csrf':'test-admin-csrf-token'}).status_code==400
