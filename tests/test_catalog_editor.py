"""Import choices, artwork and processing activation preserve operator intent."""
import io
import json
import subprocess
from app.extensions import db
from app.models import Artist, Album, MusicArtwork, MediaIngestJob, Station, Track
from app.services.music_catalog import organize_song
from app.services.analysis_queue import process_analysis
from app.services.media import set_enabled_db
from tests.test_web import app, admin_client


def post(client,path,**values):
    return client.post(path,data={'csrf':'test-admin-csrf-token',**values})


def test_catalog_creation_metadata_and_station_boundaries(app):
    client=admin_client(app);base='/admin/api/stations/test-station'
    artist=post(client,base+'/catalog/artists',name='New artist').json['id']
    assert post(client,base+'/catalog/artists',name=' NEW ARTIST ').json['id']==artist
    album=post(client,base+'/catalog/albums',name='New album',artist_id=artist).json['id']
    assert post(client,'/admin/api/stations/second-station/catalog/albums',name='Foreign',artist_id=artist).status_code==409
    song=client.get(base+'/music').json['songs'][0]
    target=base+'/song/'+song['uuid']
    assert post(client,target,data=json.dumps({'title':'Renamed','artist_id':artist,'album_id':album})).status_code==200
    saved=client.get(target).json
    assert saved['title']=='Renamed' and saved['artist_id']==artist and saved['album_id']==album
    artist2=post(client,base+'/catalog/artists',name='Other artist').json['id']
    assert post(client,target,data=json.dumps({'title':'Bad album','artist_id':artist2,'album_id':album})).status_code==409
    assert client.get('/admin/api/stations/second-station/song/'+song['uuid']).status_code==404
    assert client.post(base+'/catalog/artists',data={'name':'No CSRF'}).status_code==400


def test_artwork_upload_crops_and_serves_station_scoped(app,tmp_path):
    image=tmp_path/'cover.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=800x600','-frames:v','1',str(image)],check=True)
    client=admin_client(app);base='/admin/api/stations/test-station'
    artist=post(client,base+'/catalog/artists',name='Cover artist').json['id']
    album=post(client,base+'/catalog/albums',name='Cover album',artist_id=artist).json['id']
    result=post(client,base+'/artwork',file=(io.BytesIO(image.read_bytes()),'cover.png'),album_id=album)
    assert result.status_code==200
    response=client.get(result.json['url']);assert response.status_code==200 and response.mimetype=='image/jpeg'
    assert client.get(result.json['url'].replace('test-station','second-station')).status_code==404
    assert app.test_client().get(result.json['url']).status_code==302
    with app.app_context():assert db.session.get(Album,album).cover_id==result.json['id']
    assert post(client,base+'/artwork',file=(io.BytesIO(b'not image'),'bad.png')).status_code==400


def test_import_choices_survive_worker_and_enable_after_analysis(app,tmp_path,monkeypatch):
    from app.services import media
    from app.ingest_worker import process_one
    from app.services.media_storage import LocalMediaStorage
    uploads=tmp_path/'uploads';uploads.mkdir();app.config['FREO_UPLOAD_ROOT']=str(uploads)
    audio=tmp_path/'song.mp3'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-metadata','title=Embedded','-metadata','artist=Embedded artist',str(audio)],check=True)
    client=admin_client(app);base='/admin/api/stations/test-station'
    artist=post(client,base+'/catalog/artists',name='Chosen artist').json['id']
    album=post(client,base+'/catalog/albums',name='Chosen album',artist_id=artist).json['id']
    catalog=client.get(base+'/music').json;category=catalog['categories'][0]['id']
    # Use real staging/probing with an isolated ingest storage implementation.
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    monkeypatch.setattr(media,'_prepare_dirs',lambda storage,slug: ((tmp_path/'stored'),(tmp_path/'staging')))
    (tmp_path/'stored').mkdir();(tmp_path/'staging').mkdir()
    # Existing ingest tests own filesystem ACL mechanics; retain real audio work here.
    from app.services.media_probe import probe
    def ingest(slug,path,**kwargs):
        from app.services.music_catalog import organize_song
        import uuid,hashlib
        info=probe(path);station=Station.query.filter_by(slug=slug).one()
        song=Track(station_id=station.id,uuid=str(uuid.uuid4()),title='Embedded',artist='Embedded artist',album='',original_filename='song.mp3',storage_key='b'*32+'.mp3',media_type='mp3',duration_ms=info['duration_ms'],sample_rate_hz=info['sample_rate_hz'],channels=info['channels'],file_size_bytes=audio.stat().st_size,checksum_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),enabled=False)
        song.auto_enable_pending=kwargs.get('auto_enable_pending',False)
        db.session.add(song);organize_song(song)
        from app.services.catalog_edit import apply_metadata
        apply_metadata(song,kwargs.get('import_metadata',{}))
        db.session.commit();return song,False
    monkeypatch.setattr('app.ingest_worker.ingest',ingest)
    monkeypatch.setattr(LocalMediaStorage,'regular_file',lambda *args:audio)
    monkeypatch.setattr('app.ingest_worker.extract_artwork',lambda song:None,raising=False)
    monkeypatch.setattr('app.services.audio_analysis.extract_artwork',lambda song:None)
    metadata={'title':'Chosen title','artist_id':artist,'album_id':album,'categories':[category]}
    response=post(client,'/admin/stations/test-station/media/upload',files=(io.BytesIO(audio.read_bytes()),'song.mp3'),metadata=json.dumps(metadata))
    assert response.status_code==303
    with app.app_context():
        assert process_one()
        job=MediaIngestJob.query.filter_by(kind='ingest').one();song=job.track
        assert song.title=='Chosen title' and song.artist_id==artist and song.album_id==album
        assert song.auto_enable_pending and not song.enabled and len(song.categories)==1
        # Analyze this new import first, avoiding the unrelated fixture track.
        Track.query.filter(Track.id!=song.id).update({'analysis_status':'complete'})
        db.session.commit();assert process_analysis();db.session.refresh(song)
        assert song.analysis_status=='complete' and song.enabled and not song.auto_enable_pending
        assert len(song.waveform)>100 and max(song.waveform)>0


def test_analysis_never_reenables_manual_disable_or_decommission(app,monkeypatch):
    with app.app_context():
        song=Track.query.first();song.auto_enable_pending=True;song.enabled=False;db.session.commit()
        def analyze(song):
            # Simulate operator state arriving while ffmpeg is working.
            db.session.execute(db.update(Track).where(Track.id==song.id).values(auto_enable_pending=False,enabled=False))
            song.analysis_status='complete';song.analysis_error=''
        monkeypatch.setattr('app.services.analysis_queue.analyze_song',analyze)
        monkeypatch.setattr('app.services.analysis_queue.extract_artwork',lambda song:None)
        assert process_analysis();db.session.refresh(song);assert not song.enabled
        song.analysis_status='pending';song.auto_enable_pending=True;db.session.commit()
        def failed(song):song.analysis_status='failed';song.analysis_error='Bad audio'
        monkeypatch.setattr('app.services.analysis_queue.analyze_song',failed)
        assert process_analysis();assert not song.enabled


def test_import_migration_roundtrip_preserves_existing_rows(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    spec=importlib.util.spec_from_file_location('import_migration','migrations/versions/f61c20d9a843_media_import_experience.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite:///'+str(tmp_path/'migration.sqlite'))
    with engine.begin() as connection:
        for table in ['stations','albums','tracks','media_ingest_jobs']:
            connection.exec_driver_sql(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql(f'INSERT INTO {table} VALUES (1)')
        with Operations.context(MigrationContext.configure(connection)):migration.upgrade()
        row=connection.exec_driver_sql('SELECT auto_enable_pending,waveform FROM tracks').one()
        assert row==(0,'[]')
        with Operations.context(MigrationContext.configure(connection)):migration.downgrade()
        for table in ['stations','albums','tracks','media_ingest_jobs']:
            assert connection.exec_driver_sql(f'SELECT id FROM {table}').scalar()==1
