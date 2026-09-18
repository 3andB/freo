"""Behavioral regressions found during the September 18 importer review.

These regressions now assert the repaired behavior.
All files and database rows belong to the existing isolated test fixtures.
"""
import uuid
import pytest
from sqlalchemy import event
from app.extensions import db
from app.models import MediaIngestJob, MusicImportItem, Track
from app.services.admin_media import staged_path
from tests.test_import_sessions import app, app_fixture, audio, upload, post, prepare, finalize, BASE
from tests.test_web import admin_client


def test_worker_recovers_when_final_result_commit_is_interrupted(app,tmp_path,monkeypatch):
    from app.ingest_worker import process_one
    client=admin_client(app);session=post(client,BASE).json
    item=upload(client,session,audio(tmp_path)).json
    assert finalize(client,prepare(app,client,session)).status_code==200
    with app.app_context():
        original_commit=db.session.commit
        commits=0
        def interrupted_commit():
            nonlocal commits
            commits+=1
            if commits==3:raise RuntimeError('Simulated interruption of final job commit')
            return original_commit()
        with monkeypatch.context() as patch:
            patch.setattr(db.session,'commit',interrupted_commit)
            with pytest.raises(RuntimeError,match='Simulated interruption'):process_one()
        db.session.rollback()
        job=db.session.get(MediaIngestJob,item['id'])
        assert job.status=='processing'
        assert Track.query.filter_by(title='Song 1').count()==1
        # Mirror startup recovery, then execute the real worker again.
        job.status='pending';db.session.commit()
        process_one()
        job=db.session.get(MediaIngestJob,item['id'])
        assert job.status in ('accepted','duplicate'), (job.status,job.error_code,staged_path(item['id']).exists())
        assert job.track is not None


def test_polling_large_completed_import_has_bounded_query_count(app):
    client=admin_client(app);session=post(client,BASE).json
    with app.app_context():
        for index in range(100):
            identifier=str(uuid.uuid4())
            song=Track(station_id=1,uuid=str(uuid.uuid4()),title=f'Review {index}',artist='Review artist',album='',
                original_filename=f'{index}.mp3',storage_key=uuid.uuid4().hex+'.mp3',media_type='mp3',
                duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=100,
                checksum_sha256=str(index).zfill(64),enabled=False,ingest_status='accepted')
            job=MediaIngestJob(id=identifier,station_id=1,kind='ingest',status='accepted',original_filename=f'{index}.mp3',track=song)
            db.session.add(MusicImportItem(id=identifier,session_id=session['id'],original_filename=f'{index}.mp3',
                size_bytes=100,checksum=str(index).zfill(64),status='finalized',job=job))
        db.session.commit()
        engine=db.engine
    queries=[]
    def observe(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
    event.listen(engine,'before_cursor_execute',observe)
    try:response=client.get(session['url'])
    finally:event.remove(engine,'before_cursor_execute',observe)
    assert response.status_code==200 and len(response.json['items'])==100
    assert len(queries)<=20, f'{len(queries)} SELECT queries for one 100-song poll'


def test_deleted_song_can_be_intentionally_reimported(app,tmp_path):
    from app.ingest_worker import process_one
    from app.services.music_delete import delete_audio
    from app.models import Station
    client=admin_client(app);session=post(client,BASE).json;path=audio(tmp_path)
    upload(client,session,path);finalize(client,prepare(app,client,session))
    with app.app_context():
        process_one();song=Track.query.filter_by(title='Song 1').one();old_id=song.id
        # Disposable stations are stopped so deletion does not require engine observations.
        Station.query.update({'desired_state':'stopped'})
        delete_audio(song);db.session.commit()
    second=post(client,BASE).json
    upload(client,second,path);finalize(client,prepare(app,client,second))
    with app.app_context():
        process_one()
        song=Track.query.filter_by(title='Song 1',deleted_at=None).one()
        assert song.id!=old_id
    assert client.get(second['url']).json['items'][0]['job_status']=='accepted'


@pytest.mark.parametrize('extension',['mp3','m4a','flac','wav'])
def test_review_import_reaches_processed_broadcast_state(app,tmp_path,extension):
    from app.ingest_worker import process_one
    from app.services.analysis_queue import process_analysis
    from app.services.media_storage import LocalMediaStorage
    from app.models import MediaCategory
    client=admin_client(app);session=post(client,BASE).json
    path=audio(tmp_path,extension,artist='End to end',album='Reviewed album')
    item=upload(client,session,path).json
    review=prepare(app,client,session)
    assert client.get(review['items'][0]['preview_url']).status_code==200
    with app.app_context():category=MediaCategory.query.filter_by(station_id=1).first().id
    assert post(client,session['url']+'/items/'+item['id'],{
        'revision':review['items'][0]['revision'],'choices':{'categories':[category]}
    }).status_code==200
    assert finalize(client,client.get(session['url']).json).status_code==200
    with app.app_context():
        for _ in range(12):
            if not (process_analysis(requested=True) or process_one() or process_analysis()):break
        else:pytest.fail('Worker queue did not drain')
        song=Track.query.filter_by(artist='End to end').one()
        assert song.analysis_status=='complete' and song.enabled and not song.auto_enable_pending
        assert song.waveform and song.loudness_lufs is not None
        assert LocalMediaStorage().regular_file(song.station.slug,song.storage_key).read_bytes()==path.read_bytes()
    result=client.get(session['url']).json['items'][0]
    assert result['job_status']=='accepted'
    assert result['song']['broadcast']=='Enabled for broadcast'
    assert client.get(result['song']['audition']).status_code==200


def test_duplicate_is_identified_before_import_without_changing_existing_metadata(app,tmp_path):
    from app.ingest_worker import process_one
    client=admin_client(app);first=post(client,BASE).json;path=audio(tmp_path)
    upload(client,first,path);finalize(client,prepare(app,client,first))
    with app.app_context():
        process_one();song=Track.query.filter_by(title='Song 1').one()
        song.title='My curated title';db.session.commit();existing=song.uuid
    second=post(client,BASE).json
    response=upload(client,second,path)
    assert response.json['duplicate']['uuid']==existing
    assert response.json['duplicate']['title']=='My curated title'
    prepared=prepare(app,client,second)
    assert prepared['items'][0]['duplicate']['uuid']==existing
    assert prepared['items'][0]['song'] is None
    with app.app_context():
        assert Track.query.filter_by(uuid=existing).one().title=='My curated title'
        assert MediaIngestJob.query.count()==1
    assert client.get(second['library_url']).status_code==200
    listing=client.get(BASE.replace('/imports','/music'),query_string={'import_session':second['id']})
    assert listing.json['total']==0
    listing=client.get(BASE.replace('/imports','/music'),query_string={'import_session':first['id']})
    assert [song['uuid'] for song in listing.json['songs']]==[existing]
    with app.app_context():
        # A workspace from another station must not disclose its songs.
        from app.models import MusicImportSession,Station
        station=Station(name='Other',slug='other');db.session.add(station);db.session.flush()
        db.session.get(MusicImportSession,first['id']).station_id=station.id;db.session.commit()
    assert client.get(first['library_url']).status_code==404
    assert client.get(BASE.replace('/imports','/music'),query_string={'import_session':first['id']}).status_code==404


def test_upload_persists_validated_rotation_choice_before_preparation(app,tmp_path):
    import io
    from app.models import MediaCategory
    client=admin_client(app);session=post(client,BASE).json;path=audio(tmp_path)
    with app.app_context():category=MediaCategory.query.filter_by(station_id=1).first().id
    chosen={'categories':[category],'keep_disabled':True}
    response=post(client,session['url']+'/files',chosen,id=str(uuid.uuid4()),file=(io.BytesIO(path.read_bytes()),path.name))
    assert response.status_code==202 and response.json['choices']==chosen
    assert prepare(app,client,session)['items'][0]['choices']==chosen
    invalid=post(client,session['url']+'/files',{'categories':[999999]},id=str(uuid.uuid4()),file=(io.BytesIO(path.read_bytes()),path.name))
    assert invalid.status_code==409
    with app.app_context():assert MusicImportItem.query.count()==1


def test_retry_recovers_older_committed_song_without_staged_file(app,tmp_path):
    from app.ingest_worker import process_one
    client=admin_client(app);session=post(client,BASE).json
    item=upload(client,session,audio(tmp_path)).json
    finalize(client,prepare(app,client,session))
    with app.app_context():
        process_one();job=db.session.get(MediaIngestJob,item['id']);existing=job.track.uuid
        assert not staged_path(item['id']).exists()
        job.track_id=None;job.status='error';job.error_code='processing_failed';db.session.commit()
    current=client.get(session['url']).json['items'][0]
    assert post(client,session['url']+'/items/'+item['id'],{'action':'retry','revision':current['revision']}).status_code==200
    with app.app_context():
        process_one();job=db.session.get(MediaIngestJob,item['id'])
        assert job.status=='duplicate' and job.track.uuid==existing and job.error_code is None
        assert Track.query.filter_by(title='Song 1').count()==1


def test_staging_cleanup_failure_keeps_successful_job_durable(app,tmp_path,monkeypatch):
    from app.ingest_worker import process_one
    from pathlib import Path
    client=admin_client(app);session=post(client,BASE).json
    item=upload(client,session,audio(tmp_path)).json;finalize(client,prepare(app,client,session))
    with app.app_context():
        source=staged_path(item['id']);original=Path.unlink
        def unavailable(path,*args,**kwargs):
            if path==source:raise PermissionError('Simulated cleanup failure')
            return original(path,*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path,'unlink',unavailable)
            assert process_one()
        db.session.remove()
        job=db.session.get(MediaIngestJob,item['id'])
        assert job.status=='accepted' and job.track and source.exists()


def test_album_save_is_atomic_and_revision_checked(app,tmp_path):
    client=admin_client(app);session=post(client,BASE).json
    first=upload(client,session,audio(tmp_path,index=1)).json
    second=upload(client,session,audio(tmp_path,index=2)).json
    edits=[dict(id=first['id'],revision=1,choices={'title':'Edited one'}),
           dict(id=second['id'],revision=0,choices={'title':'Edited two'})]
    assert post(client,session['url'],{'action':'save-items','items':edits}).status_code==409
    with app.app_context():
        assert all(row.choices=={} and row.revision==1 for row in MusicImportItem.query.all())
    edits[1]['revision']=1
    saved=post(client,session['url'],{'action':'save-items','items':edits})
    assert saved.status_code==200
    assert {row['choices']['title'] for row in saved.json['items']}=={'Edited one','Edited two'}
    assert all(row['revision']==2 for row in saved.json['items'])
    another=post(client,BASE).json
    edits[0]['revision']=2
    assert post(client,another['url'],{'action':'save-items','items':[edits[0]]}).status_code==409
