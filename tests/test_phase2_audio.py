"""Track editing policy, API boundaries, refresh and compatibility."""
import json
import math
import pytest
from app.extensions import db
from app.models import Track, Station, Playlist, PlaylistItem, SelectionDecision
from app.services.track_audio import validate, effective, annotations
from app.services.loudness import gain_for
from tests.test_web import app, admin_client


def endpoint(app):
    with app.app_context():
        return '/admin/api/stations/test-station/song/'+Track.query.first().uuid+'/audio'


def save(client, url, **values):
    return client.post(url, data={'csrf':'test-admin-csrf-token', 'data':json.dumps(dict(revision=0, **values))})


@pytest.mark.parametrize('values', [dict(cue_in_ms=20000),dict(cue_in_ms=5000,cue_out_ms=4000),
    dict(cue_out_ms=20001),dict(fade_in_ms=-1),dict(fade_in_ms=11000,fade_out_ms=10000),
    dict(gain_trim_db=13),dict(gain_trim_db=float('nan')),dict(cue_in_ms=True),
    dict(cue_in_ms=1.5),dict(cue_in_ms='100'),dict(gain_trim_db=float('inf')),
    dict(cue_in_ms=10**400),dict(gain_trim_db=10**400)])
def test_invalid_audio_settings(values):
    with pytest.raises(ValueError):validate(values,20000)


def test_activation_defaults_reset_conflict_and_metadata_preservation(app):
    client=admin_client(app);url=endpoint(app)
    with app.app_context():
        song=Track.query.first();song.cue_in_ms=1234;song.cue_out_ms=18000;db.session.commit()
        assert effective(song)['cue_in_ms']==0 and song.playback_duration_ms==20000
        assert annotations(song)==''
    response=save(client,url,cue_in_ms=1000,cue_out_ms=8000,fade_in_ms=1000,fade_out_ms=2000,gain_trim_db=-3)
    assert response.status_code==200,response.json
    assert response.json['audio']['duration_ms']==7000
    assert response.json['audio']['enabled'] and response.json['audio']['revision']==1
    assert save(client,url,cue_in_ms=2000).status_code==409
    # An old advanced form cannot overwrite or activate audio edits.
    legacy=url.replace('/admin/api/stations/','/admin/stations/').replace('/song/','/media/').replace('/audio','/edit')
    result=client.post(legacy,data={'csrf':'test-admin-csrf-token','title':'Keep edits','artist':'Artist','cue_in_ms':'9999'})
    assert result.status_code==303
    with app.app_context():assert Track.query.first().cue_in_ms==1000
    response=client.post(url,data={'csrf':'test-admin-csrf-token','data':json.dumps({'revision':1})})
    assert response.status_code==200
    assert response.json['audio']['effective']==dict(cue_in_ms=0,cue_out_ms=20000,fade_in_ms=0,fade_out_ms=0,gain_trim_db=0)


def test_audio_csrf_station_and_decommission_boundaries(app):
    client=admin_client(app);url=endpoint(app)
    assert client.post(url,data={'data':'{}'}).status_code==400
    assert client.post(url,data={'csrf':'test-admin-csrf-token','data':json.dumps({'revision':10**100})}).status_code==400
    assert save(client,url.replace('test-station','second-station')).status_code==404
    assert app.test_client().post(url).status_code==302
    with app.app_context():
        from datetime import datetime,timezone
        song=Track.query.first();song.decommissioned_at=datetime.now(timezone.utc);db.session.commit()
    assert save(client,url).status_code==409


def test_trim_after_normalization_and_peak_limit(app):
    with app.app_context():
        song=Track.query.first();song.analysis_status='complete';song.loudness_lufs=-22;song.true_peak_db=-8
        original=gain_for(song);assert original['db']==6
        song.audio_edit_enabled=True;song.gain_trim_db=4
        assert gain_for(song)['db']==6.5
        song.gain_trim_db=-3;assert gain_for(song)['db']==3
        song.analysis_status='failed';assert gain_for(song)['db']==-3
        song.gain_trim_db=4;assert gain_for(song)['db']==0
        song.audio_edit_enabled=False;assert gain_for(song)['db']==0


def test_duration_sql_python_estimates_and_signature(app):
    from app.services.playlists import summaries
    from app.services.programming_refresh import signature
    from app.services.visual_schedule import source
    with app.app_context():
        song=Track.query.first();station=song.station;before=signature(station)
        song.audio_edit_enabled=True;song.cue_in_ms=1000;song.cue_out_ms=6000
        row=Playlist(station_id=station.id,name='Trimmed',items=[PlaylistItem(track=song,position=1)])
        db.session.add(row);db.session.commit()
        assert signature(station)!=before
        assert db.session.query(Track.playback_duration_ms).first()[0]==song.playback_duration_ms==5000
        assert next(r for r in summaries(station.id) if r['id']==row.id)['duration_ms']==5000
        assert source(station,dict(kind='song',id=song.id))['duration']==5
        song.cue_out_ms=500
        assert song.playback_duration_ms==20000
        db.session.flush();assert db.session.query(Track.playback_duration_ms).first()[0]==20000


def test_calendar_warnings_use_trimmed_smart_members_and_leader(app, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services import planning
    with app.app_context():
        song = Track.query.first()
        song.audio_edit_enabled = True
        song.cue_in_ms, song.cue_out_ms = 1000, 6000
        row = Playlist(station_id=song.station_id, name='Smart programme', smart_enabled=True,
                       smart_rules={}, leader_track=song)
        db.session.add(row)
        db.session.commit()
        instant = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
        first = SimpleNamespace(name='First', playlist=row, station_id=song.station_id,
            playlist_playback='ALL', track=None, imaging_asset=None, event_block=None, late_tolerance_seconds=0)
        second = SimpleNamespace(name='Second', playlist=None, track=song,
            imaging_asset=None, event_block=None, late_tolerance_seconds=0)
        monkeypatch.setattr(planning, 'coverage', lambda *args: [])
        monkeypatch.setattr('app.services.timed_events.validate_content', lambda event: True)
        from datetime import timedelta
        monkeypatch.setattr(planning, 'projected_occurrences', lambda *args: [
            SimpleNamespace(event=first, scheduled_for_utc=instant),
            SimpleNamespace(event=second, scheduled_for_utc=instant+timedelta(seconds=8))])
        assert any('earlier event' in w for w in planning.preview_days(song.station, instant.date(), 1)[0]['warnings'])
        song.cue_out_ms = 4000
        db.session.commit()
        assert planning.preview_days(song.station, instant.date(), 1)[0]['warnings'] == []


def test_reanalysis_preserves_explicit_blank_cues_during_save(app,monkeypatch):
    from app.services.analysis_queue import process_analysis
    with app.app_context():
        song=Track.query.first();song.cue_in_ms=None;song.cue_out_ms=None;db.session.commit()
        def analyze(song):
            song.cue_in_ms=500;song.cue_out_ms=18000;song.analysis_status='complete'
            # Simulate a committed editor save while the worker was analysing.
            with db.session.no_autoflush:
                db.session.execute(db.update(Track).where(Track.id==song.id).values(audio_edit_enabled=True,cue_in_ms=None,cue_out_ms=None),execution_options={'synchronize_session':False})
        monkeypatch.setattr('app.services.analysis_queue.analyze_song',analyze)
        monkeypatch.setattr('app.services.analysis_queue.extract_artwork',lambda *a:None)
        assert process_analysis();db.session.refresh(song)
        assert song.audio_edit_enabled and song.cue_in_ms is None and song.cue_out_ms is None


@pytest.mark.parametrize('bus,reason,queue', [('A','category','freo_queue'),('A','deck_load','freo_a'),('B','deck_load','freo_b'),('CART','cart','freo_cart')])
def test_request_edits_across_buses_and_legacy_cart(app,monkeypatch,bus,reason,queue):
    from app.services.playout_queue import push_decision as push
    from pathlib import Path
    with app.app_context():
        song=Track.query.first();song.storage_key='a'*32+'.mp3'
        song.audio_edit_enabled=True;song.cue_in_ms=1000;song.cue_out_ms=8000;song.fade_in_ms=500;song.fade_out_ms=1000
        row=SelectionDecision(station_id=song.station_id,track=song,playback_bus=bus,reason=reason,status='selected')
        db.session.add(row);db.session.commit()
        monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:Path('/safe') )
        seen=[];monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command:seen.append(command) or '7')
        assert push(row)==7
        assert seen[0].startswith(queue+'.push ') and 'liq_cue_in="1.000",liq_cue_out="8.000",freo_fade_in="0.500",freo_fade_out="1.000"' in seen[0]
        song.audio_edit_enabled=False
        push(row);assert 'liq_cue' in seen[-1]  # A submitted decision retains its policy.
        row.audio_snapshot=None
        push(row);assert 'liq_cue' not in seen[-1]
        if bus=='CART':assert 'freo_gain="0.000 dB"' in seen[-1]


def test_annotation_allowlist_rejects_injection(app,monkeypatch):
    from app.services.playout_queue import _command
    with app.app_context():
        for suffix in ('freo_fade_out="1.000",unknown="1"','freo_fade_out="1.000\nquit"','freo_fade_out="nan"'):
            with pytest.raises(ValueError):
                _command('test-station','freo_queue.push annotate:freo_decision=1,liq_cue_in="0.000",liq_cue_out="2.000",freo_fade_in="1.000",'+suffix+':/var/lib/freo/media/test-station/originals/'+('a'*32)+'.mp3')


def test_execution_and_submitted_duration_snapshot_survive_edits(app,monkeypatch):
    from app.models import EventBlock, EventBlockItem
    from app.services.event_blocks import create_execution, prepare_next
    from app.services.track_audio import decision_duration_ms
    from app.services.playout_queue import push_decision
    from pathlib import Path
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:Path('/safe'))
    monkeypatch.setattr('app.services.playout_queue._command',lambda *a:'12')
    with app.app_context():
        song=Track.query.first();song.audio_edit_enabled=True;song.cue_in_ms=1000;song.cue_out_ms=6000
        block=EventBlock(station_id=song.station_id,name='Fixed',slug='fixed',enabled=True,items=[EventBlockItem(position=1,item_type='TRACK',track=song)])
        db.session.add(block);db.session.commit()
        execution=create_execution(block,'MANUAL')
        song.cue_out_ms=18000;db.session.commit()
        item=prepare_next(execution);decision=item.selection_decision
        assert decision_duration_ms(decision)==5000
        uri=push_decision(decision,prepare_only=True)
        assert 'liq_cue_out="6.000"' in uri
        from app.services.live_assist import safe_item
        assert safe_item(decision)['duration_ms']==5000


@pytest.mark.parametrize('path', ['automation', 'timed_event'])
def test_snapshot_survives_crash_after_engine_acceptance(app, monkeypatch, path):
    from datetime import datetime, timezone
    from pathlib import Path
    from types import SimpleNamespace
    from app import automation_worker as worker
    from app.services.track_audio import decision_duration_ms
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *a: Path('/safe'))
    submitted = []
    def accepted_then_crashed(slug, command):
        submitted.append(command)
        raise SystemExit('Worker died after the engine accepted the request')
    monkeypatch.setattr('app.services.playout_queue._command', accepted_then_crashed)
    monkeypatch.setattr(worker, 'reconcile_requests', lambda slug: None)
    monkeypatch.setattr(worker, 'queue_depth', lambda slug: 0)
    with app.app_context():
        song = Track.query.first()
        song.audio_edit_enabled = True
        song.cue_in_ms, song.cue_out_ms = 1000, 6000
        song.gain_trim_db = -6
        row = SelectionDecision(station_id=song.station_id, track=song, status='selected')
        db.session.add(row)
        db.session.commit()
        identifier = row.id
        monkeypatch.setattr(worker, 'select_next', lambda slug: row)
        with pytest.raises(SystemExit):
            if path == 'automation':
                worker.refill_station(song.station.slug, SimpleNamespace(collect=lambda slug: None, starved_until={}))
            else:
                worker._queue_event(SimpleNamespace(selection_decision=row), song.station.slug, datetime.now(timezone.utc))
        db.session.rollback()
        db.session.expire_all()
        assert 'liq_cue_out="6.000"' in submitted[0]
        song.cue_out_ms = 18000
        song.gain_trim_db = -2
        db.session.commit()
        restored = db.session.get(SelectionDecision, identifier)
        assert decision_duration_ms(restored) == 5000
        assert restored.audio_snapshot['gain_db'] == -6
