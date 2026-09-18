"""Import review uses real audio, durable drafts and idempotent finalization."""
import io
import json
import subprocess
import uuid
from datetime import timedelta
import pytest
from app.extensions import db
from app.models import MusicImportSession, MusicImportItem, MediaIngestJob, Track, Artist, Album
from app.services.import_sessions import prepare_one, cleanup_drafts, utcnow
from app.services.admin_media import staged_path
from tests.test_web import app as app_fixture, admin_client

BASE='/admin/api/stations/test-station/imports'


@pytest.fixture
def app(app_fixture, tmp_path, monkeypatch):
    root=tmp_path/'uploads';root.mkdir();app_fixture.config['FREO_UPLOAD_ROOT']=str(root)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    return app_fixture


def post(client,url,data=None,**form):
    return client.post(url,data={'csrf':'test-admin-csrf-token','data':json.dumps(data or {}),**form})


def audio(tmp_path, extension='mp3', index=1, **tags):
    path=tmp_path/f'song-{index}.{extension}'
    cmd=['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={440+index}:duration=1']
    for key,value in {'title':f'Song {index}','artist':'Embedded artist','album':'Embedded album','track':str(index),**tags}.items():cmd+=['-metadata',f'{key}={value}']
    subprocess.run(cmd+['-y',str(path)],check=True)
    return path


def upload(client,session,path,identifier=None):
    return post(client,session['url']+'/files',id=identifier or str(uuid.uuid4()),file=(io.BytesIO(path.read_bytes()),path.name))


def prepare(app,client,session):
    with app.app_context():
        while prepare_one():pass
    return client.get(session['url']).json


def finalize(client,session):
    return post(client,session['url'],{'action':'finalize','items':[{'id':i['id'],'revision':i['revision']} for i in session['items']]})


@pytest.mark.parametrize('extension',['mp3','flac','m4a','wav'])
def test_formats_review_before_library_and_reload(app,tmp_path,extension):
    client=admin_client(app);session=post(client,BASE).json
    response=upload(client,session,audio(tmp_path,extension,disc='2',date='2025',album_artist='Album owner'))
    assert response.status_code==202
    with app.app_context():assert Track.query.count()==1 and MediaIngestJob.query.count()==0
    review=prepare(app,client,session);item=review['items'][0]
    assert item['status']=='ready' and item['detected']['artist']=='Embedded artist'
    # WAV INFO tags do not carry disc or album-artist in FFmpeg's writer.
    if extension!='wav': assert item['detected']['disc_number']==2 and item['detected']['album_artist']=='Album owner'
    assert item['detected']['release_year']==2025
    if extension != 'mp3':
        import os
        with app.app_context():
            preview = staged_path(db.session.get(MusicImportItem, item['id']).preview_id)
        acl = subprocess.check_output(['getfacl', '-n', str(preview)], text=True)
        assert f'user:{os.getuid()}:r--' in acl
    assert client.get(item['preview_url'],headers={'Range':'bytes=0-63'}).status_code==206
    assert app.test_client().get(item['preview_url']).status_code==302
    assert client.get(item['preview_url'].replace('test-station','second-station')).status_code==404
    assert client.get(BASE).json['sessions'][0]['id']==session['id']
    assert client.get(session['url']).json['items'][0]['detected']==item['detected']


def test_revisions_choices_idempotency_and_edit_after_import(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json;path=audio(tmp_path)
    identifier=str(uuid.uuid4());assert upload(client,session,path,identifier).status_code==202
    assert upload(client,session,path,identifier).json['id']==identifier
    review=prepare(app,client,session);item=review['items'][0];url=session['url']+'/items/'+identifier
    artist=post(client,BASE.replace('/imports','/catalog/artists'),name='Amber State').json['id']
    changes={'title':'My title','artist_id':artist,'keep_disabled':True,'disc_number':2}
    saved=post(client,url,{'revision':item['revision'],'choices':changes});assert saved.status_code==200
    assert post(client,url,{'revision':item['revision'],'choices':{'title':'Stale'}}).status_code==409
    assert finalize(client,review).status_code==409
    review=client.get(session['url']).json
    assert finalize(client,review).status_code==200
    assert finalize(client,review).status_code==200
    with app.app_context():
        assert MediaIngestJob.query.count()==1
        from app.ingest_worker import process_one
        assert process_one()
        song=Track.query.filter_by(title='My title').one()
        assert song.artist=='Amber State' and not song.auto_enable_pending and not song.enabled
    imported=client.get(session['url']).json['items'][0]
    changes['title']='Corrected in place';changes['artist_name']='Other';changes.pop('artist_id')
    saved=post(client,url,{'revision':imported['revision'],'choices':changes})
    assert saved.status_code==200 and saved.json['song']['title']=='Corrected in place'
    with app.app_context():assert Track.query.count()==2 and not Track.query.filter_by(title='Corrected in place').one().enabled


def test_preparation_late_result_preserves_edits_and_cancellation(app,tmp_path,monkeypatch):
    client=admin_client(app);session=post(client,BASE).json;item=upload(client,session,audio(tmp_path)).json
    url=session['url']+'/items/'+item['id']
    assert post(client,url,{'revision':1,'choices':{'title':'Typed before metadata'}}).status_code==200
    reviewed=prepare(app,client,session)['items'][0]
    assert reviewed['choices']['title']=='Typed before metadata' and reviewed['detected']['title']=='Song 1'
    assert post(client,url,{'revision':2,'action':'dismiss'}).status_code==200
    with app.app_context():cleanup_drafts();assert not staged_path(item['id']).exists()
    assert client.get(session['url']).json['items']==[]


def test_compilation_and_two_discs_keep_performing_artists(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json
    upload(client,session,audio(tmp_path,index=1,artist='Singer A',album_artist='Various Artists',disc='1'))
    upload(client,session,audio(tmp_path,index=2,artist='Singer B',album_artist='Various Artists',disc='2'))
    review=prepare(app,client,session);assert finalize(client,review).status_code==200
    with app.app_context():
        from app.ingest_worker import process_one
        assert process_one() and process_one()
        songs=Track.query.filter(Track.title.in_(['Song 1','Song 2'])).order_by(Track.title).all()
        assert len(songs)==2 and songs[0].album_id==songs[1].album_id
        assert [s.artist for s in songs]==['Singer A','Singer B']
        assert [s.disc_number for s in songs]==[1,2]
        assert songs[0].catalog_album.artist.name=='Various Artists'


def test_duplicate_keeps_existing_metadata_and_enable_intent(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json;path=audio(tmp_path)
    upload(client,session,path);finalize(client,prepare(app,client,session))
    with app.app_context():
        from app.ingest_worker import process_one
        process_one()
        song=Track.query.filter_by(title='Song 1').one();song.title='Existing title';song.auto_enable_pending=False;db.session.commit()
    second=post(client,BASE).json;item=upload(client,second,path).json
    post(client,second['url']+'/items/'+item['id'],{'revision':1,'choices':{'title':'Incoming title'}})
    finalize(client,prepare(app,client,second))
    with app.app_context():
        process_one();assert Track.query.count()==2
        song=Track.query.filter_by(title='Existing title').one();assert not song.auto_enable_pending
    result=client.get(second['url']).json['items'][0]
    assert result['job_status']=='duplicate' and result['song']['title']=='Existing title'


def test_invalid_audio_expiry_auth_and_limits(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json
    assert client.post(BASE).status_code==400
    assert app.test_client().get(BASE).status_code==302
    assert client.get(session['url'].replace('test-station','second-station')).status_code==404
    bad=tmp_path/'bad.mp3';bad.write_bytes(b'not audio')
    item=upload(client,session,bad).json;result=prepare(app,client,session)['items'][0]
    assert result['status']=='failed' and result['error']
    assert finalize(client,client.get(session['url']).json).status_code==409
    with app.app_context():
        draft=db.session.get(MusicImportSession,session['id']);draft.updated_at=utcnow()-timedelta(days=8);db.session.commit()
        cleanup_drafts();assert db.session.get(MusicImportItem,item['id']).status=='expired'
        assert not staged_path(item['id']).exists()
    empty=tmp_path/'empty.wav';empty.write_bytes(b'')
    assert upload(client,session,empty).status_code==409


def test_cleanup_keeps_active_prepared_audio_and_preview(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json;item=upload(client,session,audio(tmp_path,'flac')).json
    prepare(app,client,session)
    with app.app_context():
        import os,time
        row=db.session.get(MusicImportItem,item['id']);paths=[staged_path(row.id),staged_path(row.preview_id)]
        for path in paths:os.utime(path,(time.time()-172800,time.time()-172800))
        from app.ingest_worker import cleanup_staging
        cleanup_staging();assert all(p.exists() for p in paths)


def test_group_defaults_survive_reload_and_foreign_catalog_rejected(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json
    artist=post(client,'/admin/api/stations/second-station/catalog/artists',name='Foreign').json['id']
    assert post(client,session['url'],{'action':'group','key':'album:test','choices':{'artist_id':artist}}).status_code==409
    saved=post(client,session['url'],{'action':'group','key':'album:test','choices':{'artist_name':'Amber State'}})
    assert saved.status_code==200
    assert client.get(session['url']).json['groups']['album:test']['artist_name']=='Amber State'


def test_retry_worker_failure_uses_staged_audio_without_reupload(app,tmp_path,monkeypatch):
    client=admin_client(app);session=post(client,BASE).json
    item=upload(client,session,audio(tmp_path)).json;finalize(client,prepare(app,client,session))
    import app.ingest_worker as worker
    real=worker.ingest
    def fail(*args,**kwargs):raise OSError('temporary storage failure')
    monkeypatch.setattr(worker,'ingest',fail)
    with app.app_context():
        worker.process_one();assert staged_path(item['id']).exists()
        worker.cleanup_staging();assert staged_path(item['id']).exists()
    failed=client.get(session['url']).json['items'][0];assert failed['job_status']=='error'
    retried=post(client,session['url']+'/items/'+item['id'],{'revision':failed['revision'],'action':'retry'})
    assert retried.status_code==200
    monkeypatch.setattr(worker,'ingest',real)
    with app.app_context():worker.process_one();assert Track.query.filter_by(title='Song 1').count()==1


def test_optional_artwork_failure_does_not_reject_audio(app,tmp_path,monkeypatch):
    client=admin_client(app);session=post(client,BASE).json;upload(client,session,audio(tmp_path))
    from app.services import import_sessions
    real_probe=import_sessions.probe;real_run=subprocess.run
    def with_art(path):return {**real_probe(path),'has_artwork':True}
    def fail_art(cmd,**kwargs):
        if '0:v:0' in cmd:raise subprocess.TimeoutExpired(cmd,30)
        return real_run(cmd,**kwargs)
    monkeypatch.setattr(import_sessions,'probe',with_art);monkeypatch.setattr(subprocess,'run',fail_art)
    assert prepare(app,client,session)['items'][0]['status']=='ready'


def test_real_migration_upgrade_preserves_catalog(app,monkeypatch):
    import logging.config
    monkeypatch.setattr(logging.config,'fileConfig',lambda *args,**kwargs:None)
    with app.app_context():
        before=Track.query.first().title
        MusicImportItem.__table__.drop(db.engine);MusicImportSession.__table__.drop(db.engine)
    runner=app.test_cli_runner()
    for command in (['db','stamp','ab31e76f209d'],['db','upgrade']):
        result=runner.invoke(args=command);assert result.exit_code==0,result.output
    with app.app_context():assert Track.query.first().title==before
    assert post(admin_client(app),BASE).status_code==201


def test_worker_inherits_album_defaults_without_browser_and_respects_file_choices(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json
    artist=post(client,BASE.replace('/imports','/catalog/artists'),name='Amber State').json['id']
    group='album:["embedded artist","embedded album"]'
    assert post(client,session['url'],{'action':'group','key':group,'choices':{'artist_id':artist}}).status_code==200
    first=upload(client,session,audio(tmp_path,index=1)).json
    second=upload(client,session,audio(tmp_path,index=2)).json
    post(client,session['url']+'/items/'+second['id'],{'revision':1,'choices':{'file_fields':['artist_id'],'title':'Individual override'}})
    review=prepare(app,client,session)
    by_name={i['name']:i for i in review['items']}
    assert by_name['song-1.mp3']['choices']['artist_id']==artist
    assert by_name['song-1.mp3']['choices']['inherited_group']==group
    assert 'artist_id' not in by_name['song-2.mp3']['choices']
    assert by_name['song-2.mp3']['choices']['title']=='Individual override'
    assert finalize(client,review).status_code==200
