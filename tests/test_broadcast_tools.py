from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from concurrent.futures import Future
import io
import json
import subprocess
import wave
import pytest
from app.extensions import db
from app.models import Station, Track, SelectionDecision, AudienceSample, TimedEventOccurrence
from app.services import station_audio, broadcast_reports, bulletins
from tests.test_web import app, admin_client

BASE='/admin/stations/test-station'


def test_report_confirmed_metadata_scope_and_csv(app):
    client=admin_client(app)
    with app.app_context():
        row=SelectionDecision.query.first();song=row.track
        song.isrc='TEST12345678';song.title='=formula';broadcast_reports.capture(row)
        row.started_at=datetime.now(timezone.utc)-timedelta(seconds=5)
        db.session.add(AudienceSample(scope=row.station_id,at=int(row.started_at.timestamp()),listeners=7))
        db.session.add(SelectionDecision(station_id=row.station_id,track=song,status='queued'))
        db.session.commit(); song.title='Later edit'; db.session.commit()
    response=client.get(BASE+'/broadcast-reports')
    assert response.status_code==200,response.text
    assert '1 confirmed performances' in response.text and '=formula' in response.text
    assert 'Later edit' not in response.text and 'TEST12345678' in response.text
    export=client.get(BASE+'/broadcast-reports/performances.csv')
    assert export.status_code==200 and "'=formula" in export.text and ',7,' in export.text
    assert app.test_client().get(BASE+'/broadcast-reports').status_code==302
    assert client.get('/admin/stations/second-station/broadcast-reports').status_code==200
    assert client.get(BASE+'/broadcast-reports?range=custom&start=bad&end=bad').status_code==400


def test_pwa_shell_and_metadata(app):
    client=app.test_client()
    manifest=client.get('/admin/studio.webmanifest')
    assert manifest.mimetype=='application/manifest+json'
    assert manifest.json['scope']=='/admin/' and manifest.json['display']=='standalone'
    assert client.get(manifest.json['start_url']).status_code==302
    for icon in manifest.json['icons']:
        data=client.get(icon['src']);assert data.status_code==200 and data.data.startswith(b'\x89PNG')
    assert 'station is broadcasting' in client.get('/admin/offline').text
    worker=client.get('/admin/studio-sw.js')
    assert worker.status_code==200 and "method !== 'GET'" in worker.text
    assert 'manifest' in client.get('/admin/login').text


def test_presets_and_legacy_validation():
    for preset in station_audio.PRESETS:
        values=station_audio.validate_settings(dict(bitrate=192,preset=preset))
        assert values['agc']==(preset!='off')
    assert station_audio.validate_settings(dict(bitrate=96,agc=True))['preset']=='custom'
    for values in [dict(bitrate=192,codec='aac+'),dict(bitrate=192,preset='bad'),dict(bitrate=192,preset='custom',target=float('nan'))]:
        with pytest.raises(ValueError):station_audio.validate_settings(values)


def test_bulletin_editor_and_station_intro_validation(app):
    client=admin_client(app)
    assert client.get(BASE+'/external-bulletins').status_code==200
    form=dict(csrf='test-admin-csrf-token',name='News',url='https://example.test/news.mp3',kind='FILE',duration=180,recurrence_type='HOURLY',local_time='00:00')
    assert client.post(BASE+'/external-bulletins',data={}).status_code==400
    response=client.post(BASE+'/external-bulletins',data=form)
    assert response.status_code==303,response.text
    assert client.get(response.location).status_code==200
    with app.app_context():
        row=TimedEventOccurrence.query.first();assert row.event.content_type=='BULLETIN'
        assert row.event.timing_mode=='SOFT' and row.event.late_tolerance_seconds==300
        assert row.event.repeat_days==list(range(7))
        with pytest.raises(ValueError):bulletins.validate(row.station,dict(row.event.bulletin,intro=Track.query.first().uuid))


def test_bulletin_failed_download_does_not_reserve_event(app,monkeypatch,tmp_path):
    client=admin_client(app)
    client.post(BASE+'/external-bulletins',data=dict(csrf='test-admin-csrf-token',name='News',url='https://example.test/news.mp3',kind='FILE',duration=180,recurrence_type='HOURLY',local_time='00:00'))
    with app.app_context():
        row=TimedEventOccurrence.query.first();now=datetime.now(timezone.utc)
        job=Future();job.set_exception(ValueError('offline'))
        reader=SimpleNamespace(bulletin_jobs={row.id:job})
        seen=[];monkeypatch.setattr(bulletins,'_command',lambda *args:seen.append(args) or 'OK')
        assert not bulletins.prepare(row,reader,now)
        assert row.state=='FAILED' and not seen


def test_broadcast_migration_roundtrip(app):
    runner=app.test_cli_runner()
    for args in [('db','stamp','fa06a1b2c3d4'),('db','downgrade','f906a1b2c3d4'),('db','upgrade','fa06a1b2c3d4')]:
        result=runner.invoke(args=args);assert result.exit_code==0,result.output
    with app.app_context():assert Station.query.first().stream.bitrate==64


def test_real_presets_and_aac(tmp_path):
    lines=['settings.init.allow_root := true','settings.log.level := 2']
    for index,preset in enumerate(station_audio.PRESETS):
        target=tmp_path/f'{preset}.wav'
        # Isolate processor namespaces per process below; one output per preset.
        script=tmp_path/f'{preset}.liq'
        script.write_text('\n'.join(lines+['radio = sine(amplitude=0.2, 523.0)',
            station_audio.processing_liquidsoap(dict(bitrate=192,preset=preset)),
            'radio = limit(attack=1.0, release=100.0, threshold=-1.5, ratio=100.0, gain=0.0, radio)',
            f'output.file(%wav,{json.dumps(str(target))},radio)',
            f'output.file({station_audio.encoder_liquidsoap(dict(bitrate=96,codec="aac"))},{json.dumps(str(tmp_path/(preset+".aac")))},radio)',
            'thread.run(delay=3.0, fun () -> shutdown())']))
        result=subprocess.run(['liquidsoap',str(script)],capture_output=True,text=True,timeout=90)
        assert result.returncode==0,result.stdout+result.stderr
        with wave.open(str(target)) as audio:assert audio.getnframes()/audio.getframerate()>=2
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_name,profile','-of','json',str(tmp_path/(preset+'.aac'))]))
        assert info['streams'][0]['codec_name']=='aac' and info['streams'][0]['profile']=='LC'
        subprocess.run(['ffmpeg','-v','error','-i',str(tmp_path/(preset+'.aac')),'-f','null','-'],check=True,timeout=10)


def test_invalid_pending_processing_leaves_audio_untouched(app,monkeypatch):
    from contextlib import nullcontext
    from app.services import station_runtime
    with app.app_context():
        station=Station.query.first();station.stream.pending_audio={'bitrate':192,'preset':'broken'}
        station.stream.audio_status='pending';db.session.commit()
        monkeypatch.setattr(station_runtime,'require_root',lambda:None)
        monkeypatch.setattr(station_runtime,'operation_lock',nullcontext)
        called=[];monkeypatch.setattr(station_runtime,'apply_audio',lambda *a:called.append(a))
        station_audio.process_audio(station)
        assert not called and station.stream.audio_status=='failed' and station.stream.bitrate==64


def test_report_dst_and_missing_audience(app):
    with app.app_context():
        station=Station.query.first();station.timezone='America/New_York'
        result=broadcast_reports.summary(station,{'range':'custom','start':'2026-03-08','end':'2026-03-08'})
        assert result['period']['end']-result['period']['start']==23*3600
        row=SelectionDecision.query.first();row.started_at=datetime(2026,3,8,12,tzinfo=timezone.utc);db.session.commit()
        performance=list(broadcast_reports.performances(station,result['period']))[0]
        assert performance['listeners'] is None and performance['local_time'].endswith('-04:00')


def test_live_apply_does_not_restart_station(app,monkeypatch,tmp_path):
    from app.services import station_runtime as runtime
    from contextlib import nullcontext
    with app.app_context():
        station=Station.query.first();station.stream.audio_revision=2;db.session.commit()
        monkeypatch.setattr(runtime,'ROOT',tmp_path);monkeypatch.setattr(runtime,'CONFIGS',tmp_path)
        monkeypatch.setattr(runtime,'require_root',lambda:None)
        monkeypatch.setattr(runtime,'operation_lock',nullcontext)
        monkeypatch.setattr(runtime,'credential',lambda slug:'a'*64)
        monkeypatch.setattr(runtime,'run_checked',lambda args:None)
        monkeypatch.setattr(runtime.os,'chown',lambda *args:None)
        target=tmp_path/(station.slug+'.liq');target.write_text('freo_processor live endpoint')
        restarts=[];monkeypatch.setattr(runtime,'service_action',lambda *args:restarts.append(args))
        commands=[];monkeypatch.setattr('app.services.playout_queue._command',lambda slug,cmd:commands.append(cmd) or 'OK')
        runtime.apply_audio(station,station_audio.validate_settings(dict(bitrate=64,preset='standard')))
        assert commands and commands[0].startswith('freo_processor.apply ') and not restarts


@pytest.mark.parametrize('failure',[False,True],ids=['off','constructor-failure'])
def test_real_off_matches_baseline_and_constructor_failure_bypasses(tmp_path,failure):
    limiter='limit(attack=1.0, release=100.0, threshold=-1.5, ratio=100.0, gain=0.0, radio)'
    base=tmp_path/'baseline.wav';off=tmp_path/'off.wav'
    script=tmp_path/'off.liq'
    processing=station_audio.processing_liquidsoap(dict(bitrate=192,preset='standard' if failure else 'off'))
    if failure: processing=processing.replace('agc = normalize(target={pv(3)}', 'forced_failure = list.nth([0.0],2)\n  agc = normalize(target={pv(3)+forced_failure}')
    script.write_text('settings.init.allow_root := true\nsettings.log.level := 2\nradio = sine(amplitude=0.2,523.0)\n'+
        f'output.file(%wav,{json.dumps(str(base))},{limiter})\n'+processing+
        f'\noutput.file(%wav,{json.dumps(str(off))},{limiter})\nthread.run(delay=2.0, fun () -> shutdown())')
    result=subprocess.run(['liquidsoap',str(script)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    with wave.open(str(base)) as a,wave.open(str(off)) as b:
        assert a.readframes(a.getnframes())==b.readframes(b.getnframes())


def test_file_fetch_decodes_locally_and_removes_partial_files(tmp_path,monkeypatch):
    import struct
    raw=io.BytesIO()
    with wave.open(raw,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
        wav.writeframes(struct.pack('<h',1000)*8000)
    def connection(data):
        source=io.BytesIO(data)
        response=SimpleNamespace(getheader=lambda name:None,read1=source.read1,close=source.close)
        return SimpleNamespace(_relay_socket=SimpleNamespace(settimeout=lambda value:None),close=lambda:None),response,'audio/wav'
    monkeypatch.setattr(bulletins,'open_upstream',lambda *args:connection(raw.getvalue()))
    result=bulletins.fetch_file('https://example.test/audio','',tmp_path,1)
    assert result['duration']==1 and (tmp_path/'1.wav').is_file() and not (tmp_path/'1.download').exists()
    monkeypatch.setattr(bulletins,'open_upstream',lambda *args:connection(b'not audio'))
    with pytest.raises(subprocess.CalledProcessError):bulletins.fetch_file('https://example.test/audio','',tmp_path,2)
    assert not (tmp_path/'2.wav').exists() and not (tmp_path/'2.download').exists()


def test_bulletin_confirmation_idempotent_and_restart_fails_safe(app,monkeypatch,tmp_path):
    client=admin_client(app)
    client.post(BASE+'/external-bulletins',data=dict(csrf='test-admin-csrf-token',name='Live news',url='https://example.test/live',kind='LIVE',duration=30,recurrence_type='HOURLY',local_time='00:00'))
    app.config['FREO_BULLETIN_ROOT']=str(tmp_path)
    with app.app_context():
        occurrence=TimedEventOccurrence.query.first();now=datetime.now(timezone.utc)
        occurrence.scheduled_for_utc=now-timedelta(seconds=10);occurrence.deadline_at_utc=now+timedelta(seconds=300)
        occurrence.state='QUEUED';occurrence.runtime=dict(bulletin=occurrence.event.bulletin,identity='engine1',prepared_at=now.isoformat(),duration=30,title='Live news')
        db.session.commit()
        identity=['engine1'];monkeypatch.setattr(bulletins,'socket_identity',lambda slug:identity[0])
        state=[f'{occurrence.id}|BODY|{(now-timedelta(seconds=1)).timestamp()}'];commands=[]
        def engine(slug,command):
            commands.append(command)
            return state[0] if command.endswith('.state') else 'OK'
        monkeypatch.setattr(bulletins,'_command',engine)
        reader=SimpleNamespace()
        assert bulletins.reconcile(occurrence.station,reader,now)
        assert bulletins.reconcile(occurrence.station,reader,now)
        assert SelectionDecision.query.filter_by(selection_method='bulletin').count()==1
        confirmed=SelectionDecision.query.filter_by(selection_method='bulletin').one()
        SelectionDecision.query.filter(SelectionDecision.id != confirmed.id).update(
            {'started_at': now-timedelta(seconds=10)})
        assert bulletins.current_body(occurrence.station,'engine1') == (True,confirmed.id)
        assert bulletins.current_body(occurrence.station,'different-engine') == (True,None)
        other=Station.query.filter_by(slug='second-station').one()
        assert bulletins.current_body(other,'engine1') == (True,None)
        from app.models import LiveQueueSnapshot
        snapshot=LiveQueueSnapshot(station_id=occurrence.station_id,observed_at=now,
            current_decision_id=confirmed.id,queued_decision_ids=[])
        db.session.add(snapshot);db.session.commit()
        from app.services.player import now_playing
        from app.services.live_assist import safe_item
        with app.test_request_context('/'):
            public=now_playing(occurrence.station)
        assert public['current'][0]['title']=='Live news'
        assert public['recent'][0]['title']=='Live news'
        assert not public['current'][0]['votable']
        assert safe_item(confirmed)['title']=='Live news'
        assert client.get('/admin/api/stations/test-station/now').json['now_playing']['title']=='Live news'
        identity[0]='engine2'
        assert not bulletins.reconcile(occurrence.station,reader,now)
        assert occurrence.state=='FAILED' and occurrence.failure_reason=='bulletin_engine_restarted'
        assert SelectionDecision.query.filter_by(selection_method='bulletin').count()==1


def test_changed_bulletin_discards_old_download(app,monkeypatch,tmp_path):
    client=admin_client(app)
    client.post(BASE+'/external-bulletins',data=dict(csrf='test-admin-csrf-token',name='News',url='https://example.test/news.mp3',kind='FILE',duration=180,recurrence_type='HOURLY',local_time='00:00'))
    app.config['FREO_BULLETIN_ROOT']=str(tmp_path)
    with app.app_context():
        occurrence=TimedEventOccurrence.query.first()
        folder=tmp_path/str(occurrence.station_id);folder.mkdir();target=folder/f'{occurrence.id}.wav';target.write_bytes(b'old bulletin')
        occurrence.revision=2;occurrence.runtime=dict(bulletin=occurrence.event.bulletin,fetch_revision=1,fetch_started='old')
        job=Future();job.set_result(dict(path=str(target),duration=20))
        reader=SimpleNamespace(bulletin_jobs={occurrence.id:job})
        commands=[];monkeypatch.setattr(bulletins,'_command',lambda *args:commands.append(args))
        assert not bulletins.prepare(occurrence,reader,datetime.now(timezone.utc))
        assert not commands and not target.exists() and not reader.bulletin_jobs


def test_processor_rollback_restores_live_without_restart(app,monkeypatch,tmp_path):
    from app.services import station_runtime as runtime
    with app.app_context():
        station=Station.query.first();station.stream.audio_revision=2;db.session.commit()
        monkeypatch.setattr(runtime,'CONFIGS',tmp_path)
        monkeypatch.setattr(runtime.os,'chown',lambda *args:None)
        old=runtime.render_liquidsoap(station,'a'*64)
        (tmp_path/(station.slug+'.liq')).write_text(runtime.render_liquidsoap(station,'a'*64,dict(bitrate=64,preset='punchy')))
        backup=runtime.audio_backup(station);backup.write_text(old)
        commands=[];restarts=[]
        monkeypatch.setattr('app.services.playout_queue._command',lambda slug,cmd:commands.append(cmd) or 'OK')
        monkeypatch.setattr(runtime,'service_action',lambda *args:restarts.append(args))
        runtime.restore_audio(station)
        assert commands==[station_audio.processor_command(dict(bitrate=64,preset='off'))] and not restarts
        assert not backup.exists() and (tmp_path/(station.slug+'.liq')).read_text()==old


def test_downgrade_refuses_aac_and_report_filters_are_closed(app,caplog):
    client=admin_client(app)
    assert client.get(BASE+'/broadcast-reports?slug=other&kind=other&page=1').status_code==200
    runner=app.test_cli_runner();assert runner.invoke(args=['db','stamp','fa06a1b2c3d4']).exit_code==0
    with app.app_context():
        Station.query.first().stream.format='aac';db.session.commit()
    result=runner.invoke(args=['db','downgrade','f906a1b2c3d4'])
    assert result.exit_code!=0 and 'Remove bulletins and apply MP3' in result.output+caplog.text
