"""Phase 8 permissions, provider boundaries, real rendering and ordinary ingest."""
import base64
from io import BytesIO
import json
import os
import subprocess
from uuid import uuid4
from datetime import timedelta
from unittest.mock import Mock
import pytest
from cryptography.fernet import Fernet
from app import models as m
from app.extensions import db
from app.services import production as service, production_providers as provider, production_audio as audio, production_worker as worker
from tests.test_web import app, admin_client
from tests.test_phase3_dj import dj_client

BASE='/admin/stations/test-station/production'
CSRF='test-admin-csrf-token'


@pytest.fixture
def production_app(app,tmp_path,monkeypatch):
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    root=tmp_path/'production';root.mkdir()
    uploads=tmp_path/'uploads';uploads.mkdir()
    app.config.update(FREO_PROVIDER_ENCRYPTION_KEY=Fernet.generate_key().decode(),FREO_PRODUCTION_ROOT=str(root),FREO_UPLOAD_ROOT=str(uploads),FREO_MEDIA_ROOT=str(tmp_path/'media'))
    monkeypatch.setattr('app.services.media.require_ingest_identity',lambda:None)
    monkeypatch.setattr(os,'chown',lambda *args:None)
    monkeypatch.setattr('grp.getgrnam',lambda _:type('Group',(),{'gr_gid':os.getgid()})())
    monkeypatch.setattr('pwd.getpwnam',lambda _:type('User',(),{'pw_uid':os.getuid()})())
    with app.app_context():
        m.Track.query.update({'analysis_status':'complete'})
        admin=m.AdminUser.query.first();admin.installation_admin=True
        station=m.Station.query.filter_by(slug='test-station').one()
        db.session.add(m.StationProduction(station_id=station.id,enabled=True,script_provider='openai'))
        for name in provider.PROVIDERS:provider.save_credential(name,'secret-api-key-123','test-model',0)
        db.session.commit()
    return app


def post(client,url,data=None,csrf=CSRF,**extra):
    return client.post(url,data=dict(csrf=csrf,data=json.dumps(data or {}),**extra))


def draft(client,mode='ai'):
    result=post(client,BASE+'/drafts',dict(mode=mode,title='KXYZ station ID',subtype='station_id'))
    assert result.status_code==201,result.text
    return result.json


def action(client,row,name,data=None,**extra):
    return post(client,BASE+'/'+row['id']+'/'+name,data,revision=str(row['revision']),request_id=str(uuid4()),**extra)


def fixture_audio(tmp_path,extension='mp3',duration=1):
    target=tmp_path/('tone.'+extension)
    subprocess.run(['/usr/bin/ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency=440:duration={duration}','-y',str(target)],check=True,timeout=20)
    return target.read_bytes()


def test_settings_encryption_permissions_and_redaction(production_app,dj_client):
    client=admin_client(production_app)
    assert dj_client.get('/admin/providers').status_code==403
    assert client.get('/admin/providers').status_code==200
    assert 'secret-api-key-123' not in client.get('/admin/providers').text
    assert client.post('/admin/providers',data={'provider':'elevenlabs'}).status_code==400
    with production_app.app_context():
        row=db.session.get(m.ProviderCredential,'elevenlabs')
        assert 'secret-api-key-123' not in row.ciphertext
        assert provider.credential('elevenlabs')[0]=='secret-api-key-123'
        assert 'secret-api-key-123' not in str(m.AuditEvent.query.all())
    response=client.post('/admin/providers',data=dict(csrf=CSRF,provider='elevenlabs',revision='1',action='remove'))
    assert response.status_code==200
    with production_app.app_context():
        with pytest.raises(provider.ProviderError):provider.credential('elevenlabs')
    assert client.get(BASE).status_code==200
    assert post(client,BASE+'/drafts',dict(mode='voice',title='Manual voice')).status_code==201


def test_dj_grants_station_scope_and_admin_boundaries(production_app,dj_client):
    assert dj_client.get(BASE).status_code==403
    with production_app.app_context():
        dj=m.AdminUser.query.filter_by(role='DJ').one();station=m.Station.query.filter_by(slug='test-station').one()
        db.session.add(m.ProductionGrant(user_id=dj.id,station_id=station.id,voice_tracking=True,ai_generation=False));db.session.commit()
    assert dj_client.get(BASE).status_code==200
    assert post(dj_client,BASE+'/drafts',dict(mode='ai',title='No'),csrf='dj-csrf').status_code==403
    response=post(dj_client,BASE+'/drafts',dict(mode='voice',title='My link'),csrf='dj-csrf')
    assert response.status_code==201
    identifier=response.json['id']
    for path in ('/admin/providers',BASE+'/settings','/admin/stations/test-station/settings'):
        assert dj_client.get(path).status_code==403
    assert dj_client.get('/admin/stations/second-station/production/'+identifier).status_code==403
    other=draft(admin_client(production_app),'voice')
    assert dj_client.get(BASE+'/'+other['id']).status_code==403
    with production_app.app_context():
        m.ProductionGrant.query.one().voice_tracking=False;db.session.commit()
    assert dj_client.get(BASE+'/'+identifier).status_code==403


def test_script_jobs_idempotent_and_revocation(production_app,monkeypatch):
    client=admin_client(production_app);row=draft(client)
    callback=Mock(return_value=('You are listening to KXYZ.',{'input_tokens':20,'output_tokens':9}))
    monkeypatch.setattr(provider,'write_script',callback)
    request_id=str(uuid4())
    for _ in range(2):
        result=post(client,BASE+'/'+row['id']+'/script',dict(prompt='Rock station ID',seconds=8),revision='1',request_id=request_id)
        assert result.status_code==200,result.text
    with production_app.app_context():
        assert m.ProductionAttempt.query.count()==1
        assert worker.process_one()
        assert callback.call_count==1
        record=m.ProductionDraft.query.one()
        assert record.spec['script']=='You are listening to KXYZ.'
        assert not record.track_id
        assert m.ProductionAttempt.query.one().usage['input_tokens']==20
    row=client.get(BASE+'/'+row['id']).json
    result=action(client,row,'script',dict(prompt='Another script'))
    assert result.status_code==200
    with production_app.app_context():
        db.session.get(m.StationProduction,1).enabled=False;db.session.commit()
        worker.process_one()
        assert callback.call_count==1
        assert m.ProductionAttempt.query.order_by(m.ProductionAttempt.created_at.desc()).first().status=='failed'


def test_voice_music_fx_design_and_failure_retains_preview(production_app,monkeypatch,tmp_path):
    raw=fixture_audio(tmp_path)
    monkeypatch.setattr(provider,'models',lambda:[dict(id='test-tts',name='Test',style=True,similarity=True)])
    calls=[]
    def call(name,path,payload=None,**kwargs):
        calls.append((path,payload))
        if path=='/v1/text-to-voice/design':return {'previews':[dict(audio_base_64=base64.b64encode(raw).decode(),generated_voice_id='design-1')]},{}
        if path=='/v1/text-to-voice':return {'voice_id':'saved-voice'},{}
        return raw,{'character-cost':'12'}
    monkeypatch.setattr(provider,'call',call)
    client=admin_client(production_app);row=draft(client)
    for name,values in [('voice',dict(script='KXYZ',voice_id='voice-1',model_id='test-tts')),
                        ('bed',dict(prompt='Rock bed',seconds=10)),('fx',dict(prompt='Impact',seconds=2)),
                        ('design',dict(description='A warm deep energetic radio announcer')),
                        ('save_voice',dict(generated_voice_id='design-1',name='My voice')),
                        ('render',dict(voice_level=0,bed_level=-18,fx_level=-12,fade=.1))]:
        result=action(client,row,name,values);assert result.status_code==200,result.text
        with production_app.app_context():assert worker.process_one()
        row=client.get(BASE+'/'+row['id']).json
        assert row['attempts'][0]['status']=='complete',row
    assert any(payload.get('force_instrumental') is True for _,payload in calls)
    assert row['spec']['voice_id']=='saved-voice'
    assert client.get(row['components']['render']).status_code==200
    prior=row['components']['render'].split('?')[0]
    monkeypatch.setattr(provider,'call',Mock(side_effect=provider.ProviderError('Provider quota exhausted.')))
    result=action(client,row,'bed',dict(prompt='New bed'));assert result.status_code==200
    with production_app.app_context():worker.process_one()
    row=client.get(BASE+'/'+row['id']).json
    assert row['components']['render'].split('?')[0]==prior
    assert row['attempts'][0]['status']=='failed'
    with production_app.app_context():assert m.Track.query.count()==1


def test_recording_real_render_ingest_and_normal_station_asset(production_app,tmp_path):
    client=admin_client(production_app);row=draft(client,'voice')
    raw=fixture_audio(tmp_path,'webm')
    result=action(client,row,'upload',audio=(BytesIO(raw),'recording.webm'))
    assert result.status_code==200,result.text
    with production_app.app_context():assert worker.process_one()
    row=client.get(BASE+'/'+row['id']).json
    assert row['components']['render']
    result=action(client,row,'save');assert result.status_code==200,result.text
    with production_app.app_context():
        assert worker.process_one()
        record=m.ProductionDraft.query.one()
        assert record.state=='ingesting' and record.ingest_job_id
        from app.ingest_worker import process_one
        assert process_one()
        job=db.session.get(m.MediaIngestJob,record.ingest_job_id)
        assert job.status=='accepted',job.error_code
        track=job.track
        assert track.audio_kind=='STATION' and track.audio_subtype=='voice_track'
        assert not track.enabled and not track.available_to_all
        assert record.track_id==track.id
        from app.services.analysis_queue import process_analysis
        assert process_analysis()
        worker.reconcile()
        assert record.state=='saved' and track.enabled
        collection=m.Playlist.query.filter_by(station_id=record.station_id,system_key='STATION').one()
        assert track.id in [i.track_id for i in collection.items]
        from app.services.playlists import configure, leader_track
        playlist=m.Playlist(station_id=record.station_id,name='Show');db.session.add(playlist);db.session.flush()
        playlist.leader_track=track
        assert leader_track(playlist).id==track.id
        preview_url=BASE+'/'+record.id+'/preview/render'
        # Saved previews use the ordinary catalog file, not the private render.
        audio.path(record.components['render']).unlink()
        assert client.get(preview_url).status_code==200
        track.deleted_at=worker.now();db.session.commit()
        assert client.get(preview_url).status_code==404
        worker.cleanup();assert record.state=='deleted'


def test_invalid_inputs_recovery_cleanup_and_duration(production_app,tmp_path):
    with production_app.app_context():
        key=audio.store(b'not audio')
        with pytest.raises(ValueError):audio.render({'voice':key},{},60)
        key=audio.store(fixture_audio(tmp_path,duration=2))
        with pytest.raises(ValueError):audio.inspect(key,1)
        with pytest.raises(ValueError):audio.render({'voice':key},{'voice_level':float('nan')},60)
        with pytest.raises(ValueError):audio.path('../secret')
        user=m.AdminUser.query.first();station=m.Station.query.first()
        record=service.create(station,user,'ai','Test','station_id');db.session.flush()
        job=service.enqueue(record,user,'script',dict(prompt='Test'),str(uuid4()),1);job.status='running';db.session.commit()
        worker.recover();assert job.status=='failed'
        assert not worker.process_one()
        record.updated_at=worker.now()-timedelta(days=8);db.session.commit();worker.cleanup()
        assert record.state=='expired'


def test_provider_errors_and_bounded_network(monkeypatch):
    from urllib.error import HTTPError, URLError
    for code,expected in [(401,'invalid'),(403,'capability'),(429,'quota'),(500,'failed')]:
        opener=Mock();opener.open.side_effect=HTTPError('https://api.test',code,'SECRET-ERROR',{},None)
        monkeypatch.setattr(provider,'build_opener',lambda *args:opener)
        with pytest.raises(provider.ProviderError,match=expected) as error:provider.exchange('https://api.test',{'Authorization':'secret'})
        assert 'SECRET' not in str(error.value)
    opener.open.side_effect=URLError('secret error')
    with pytest.raises(provider.ProviderError,match='timed out'):provider.exchange('https://api.test',{})


def test_migration_roundtrip_preserves_prior_phases(production_app):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('phase8','migrations/versions/f806a1b2c3d4_audio_production.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with production_app.app_context():
        with db.engine.begin() as connection:
            migration.op=Operations(MigrationContext.configure(connection));migration.downgrade();migration.upgrade()
        assert m.Station.query.count()==2 and m.Track.query.count()==1
        assert m.ProviderCredential.query.count()==0
        assert m.StationProduction.query.count()==0


def test_station_settings_roundtrip_and_defaults(production_app,dj_client):
    client=admin_client(production_app)
    assert client.get(BASE+'/settings').status_code==200
    with production_app.app_context():
        user=m.AdminUser.query.filter_by(role='DJ').one();station=m.Station.query.first()
        playlist=m.Playlist(station_id=station.id,name='DJ show');db.session.add(playlist);db.session.commit()
        values=dict(revision=1,enabled=True,script_provider='anthropic',voice_id='default',model_id='test-model',
                    grants=[dict(user_id=user.id,voice_tracking=True,ai_generation=True,playlists=[playlist.id])])
    assert post(client,BASE+'/settings',values).status_code==200
    assert post(client,BASE+'/settings',values).status_code==400
    assert dj_client.get(BASE).status_code==200
    assert post(dj_client,BASE+'/drafts',dict(mode='ai',title='AI DJ image',subtype='promo'),csrf='dj-csrf').status_code==201
    with production_app.app_context():
        assert m.ProductionGrant.query.one().ai_generation
        assert m.ProductionDraft.query.one().spec['voice_id']=='default'
    assert client.get('/admin/stations/second-station/production/settings').status_code==200
    assert post(client,'/admin/stations/second-station/production/drafts',dict(mode='ai',title='No',subtype='promo')).status_code==403


def saved_voice(station,user,code):
    track=m.Track(station_id=station.id,uuid=str(uuid4()),title='Voice '+code,artist='DJ',original_filename='voice.mp3',
        storage_key=uuid4().hex+'.mp3',media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,
        file_size_bytes=100,checksum_sha256=code*64,enabled=True,ingest_status='accepted',audio_kind='STATION',audio_subtype='voice_track')
    db.session.add(track);db.session.flush()
    row=service.create(station,user,'voice','Voice '+code,'voice_track');row.track=track;row.state='saved'
    db.session.flush();return row


def test_granted_playlist_insert_replace_revisions_and_delete(production_app,dj_client):
    with production_app.app_context():
        user=m.AdminUser.query.filter_by(role='DJ').one();station=m.Station.query.first()
        playlist=m.Playlist(station_id=station.id,name='Granted');outside=m.Playlist(station_id=station.id,name='Outside')
        db.session.add_all([playlist,outside]);db.session.flush()
        db.session.add(m.ProductionGrant(user_id=user.id,station_id=station.id,voice_tracking=True,playlists=[playlist.id]));db.session.flush()
        first=saved_voice(station,user,'b');second=saved_voice(station,user,'c')
        music=m.Track.query.filter_by(audio_kind='MUSIC').one()
        from app.services.playlists import replace_order,ordered_ids
        replace_order(playlist,[music.id]);db.session.commit()
        service.place(first,user,dict(playlist_id=playlist.id,revision=playlist.revision,position=1))
        db.session.commit();assert ordered_ids(playlist)==[music.id,first.track_id]
        with pytest.raises(ValueError,match='changed'):service.place(second,user,dict(playlist_id=playlist.id,revision=1,position=1))
        with pytest.raises(PermissionError):service.place(second,user,dict(playlist_id=outside.id,revision=outside.revision))
        with pytest.raises(ValueError):service.place(second,user,dict(playlist_id=playlist.id,revision=playlist.revision,operation='replace',replace_id=music.id))
        service.place(second,user,dict(playlist_id=playlist.id,revision=playlist.revision,operation='replace',replace_id=first.track_id))
        db.session.commit();assert ordered_ids(playlist)==[music.id,second.track_id]
        assert first.track.enabled
        replace_order(outside,[second.track_id]);db.session.commit()
        with pytest.raises(ValueError,match='other playlists'):service.delete(second,user)
        replace_order(outside,[]);station.desired_state='stopped';db.session.commit()
        service.delete(second,user);db.session.commit()
        assert second.state=='deleted' and not second.track.enabled
        assert ordered_ids(playlist)==[music.id]
        assert m.MediaIngestJob.query.filter_by(kind='delete',track_id=second.track_id).count()==1


def test_credential_rotation_cancels_queued_paid_call(production_app,monkeypatch):
    callback=Mock();monkeypatch.setattr(provider,'write_script',callback)
    client=admin_client(production_app);row=draft(client)
    assert action(client,row,'script',dict(prompt='New station ID')).status_code==200
    with production_app.app_context():
        provider.save_credential('openai','replacement-key','model',1);db.session.commit()
        worker.process_one()
        assert m.ProductionAttempt.query.one().status=='failed'
        assert 'changed' in m.ProductionAttempt.query.one().error
        callback.assert_not_called()


@pytest.mark.parametrize('provider_name,response,expected_path',[('openai',{'output':[{'type':'message','content':[{'type':'output_text','text':'KXYZ rocks'}]}], 'usage':{'input_tokens':10}},'/v1/responses'),('xai',{'output':[{'type':'message','content':[{'type':'output_text','text':'KXYZ rocks'}]}]},'/v1/responses'),('anthropic',{'content':[{'type':'text','text':'KXYZ rocks'}]},'/v1/messages')])
def test_script_provider_wire_contracts(monkeypatch,provider_name,response,expected_path):
    call=Mock(return_value=(response,{}));monkeypatch.setattr(provider,'call',call)
    script,usage=provider.write_script(provider_name,'configured-model','Station ID',8,4)
    assert script=='KXYZ rocks'
    assert call.call_args.args[1]==expected_path
    assert call.call_args.args[2]['model']=='configured-model'
    assert call.call_args.kwargs['revision']==4
    assert 'KXYZ' not in call.call_args.args[2].get('instructions','')


def test_timeout_no_retry_and_duplicate_save_does_not_claim_catalog(production_app,monkeypatch,tmp_path):
    client=admin_client(production_app);row=draft(client)
    callback=Mock(side_effect=provider.ProviderError('Timed out; check usage.'));monkeypatch.setattr(provider,'write_script',callback)
    action(client,row,'script',dict(prompt='A liner'))
    with production_app.app_context():
        worker.process_one();assert not worker.process_one();callback.assert_called_once()
        row=m.ProductionDraft.query.one();key=audio.store(fixture_audio(tmp_path))
        row.components={'render':key,'voice':key}
        import hashlib
        m.Track.query.first().checksum_sha256=hashlib.sha256(audio.path(key).read_bytes()).hexdigest();db.session.commit();identifier=row.id
    row=client.get(BASE+'/'+identifier).json
    action(client,row,'save')
    with production_app.app_context():
        worker.process_one();record=m.ProductionDraft.query.one()
        assert record.track_id is None and record.state=='draft'
        assert 'already exists' in record.error
        assert m.Track.query.first().audio_kind=='MUSIC'
        assert m.MediaIngestJob.query.count()==0


def test_secret_decryption_missing_key_and_preview_origin(production_app,monkeypatch):
    with production_app.app_context():
        production_app.config['FREO_PROVIDER_ENCRYPTION_KEY']=''
        with pytest.raises(provider.ProviderError,match='encryption'):provider.credential('openai')
        production_app.config['FREO_PROVIDER_ENCRYPTION_KEY']=Fernet.generate_key().decode()
        with pytest.raises(provider.ProviderError,match='decrypt'):provider.credential('openai')
        monkeypatch.setattr(provider,'call',lambda *a,**kw:({'preview_url':'http://127.0.0.1/private'},{}))
        exchange=Mock();monkeypatch.setattr(provider,'exchange',exchange)
        with pytest.raises(provider.ProviderError):provider.voice_preview('some-voice')
        exchange.assert_not_called()


def test_interrupted_ingest_retry_reuses_only_its_own_track(production_app,tmp_path):
    client=admin_client(production_app);row=draft(client,'voice')
    action(client,row,'upload',audio=(BytesIO(fixture_audio(tmp_path)),'voice.mp3'))
    with production_app.app_context():worker.process_one()
    row=client.get(BASE+'/'+row['id']).json;action(client,row,'save')
    with production_app.app_context():
        worker.process_one()
        from app.ingest_worker import process_one
        process_one()
        record=m.ProductionDraft.query.one();identifier=record.id;track_id=record.track_id
        job=db.session.get(m.MediaIngestJob,record.ingest_job_id)
        # Ingest committed the accepted file; simulate interruption reporting error.
        job.status='error';db.session.commit();worker.reconcile()
        assert record.state=='draft' and not record.track.enabled
    row=client.get(BASE+'/'+identifier).json;assert action(client,row,'save').status_code==200
    with production_app.app_context():
        worker.process_one();process_one()
        record=m.ProductionDraft.query.one()
        assert record.track_id==track_id
        assert db.session.get(m.MediaIngestJob,record.ingest_job_id).status=='duplicate'
        assert m.Track.query.count()==2


def test_http_headers_and_response_size_are_bounded(production_app,monkeypatch):
    original_exchange=provider.exchange
    with production_app.app_context():
        exchange=Mock(return_value=({},{}));monkeypatch.setattr(provider,'exchange',exchange)
        provider.call('elevenlabs','/v2/voices')
        assert exchange.call_args.args[1]=={'xi-api-key':'secret-api-key-123'}
        assert exchange.call_args.kwargs['timeout']==15
        provider.call('openai','/v1/responses',{'model':'x'})
        assert exchange.call_args.args[1]=={'Authorization':'Bearer secret-api-key-123'}
        assert exchange.call_args.kwargs['timeout']==180
    monkeypatch.setattr(provider,'exchange',original_exchange)
    response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.read.return_value=b'x'*10;response.headers={}
    opener=Mock();opener.open.return_value=response
    monkeypatch.setattr(provider,'build_opener',lambda *a:opener);monkeypatch.setattr(provider,'LIMIT',5)
    with pytest.raises(provider.ProviderError,match='limit'):provider.exchange('https://api.test',{})
    assert provider.NoRedirect().redirect_request(None,None,None,None,None,None) is None


def test_disabling_ai_keeps_admin_history_but_blocks_new_generation(production_app):
    client=admin_client(production_app);row=draft(client)
    with production_app.app_context():
        m.StationProduction.query.one().enabled=False;db.session.commit()
    assert client.get(BASE+'/'+row['id']).status_code==200
    assert any(x['id']==row['id'] for x in client.get(BASE+'/drafts').json['drafts'])
    assert action(client,row,'script',dict(prompt='Should not run')).status_code==403
    assert action(client,row,'delete').status_code==200
