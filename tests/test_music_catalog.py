"""Artist/Album/Song catalog stays distinct from station programming."""
from app.extensions import db
from app.models import Artist,Album,MediaCategory,Station,Track
from app.services.music_catalog import bulk_categories,organize_song
from tests.test_web import app as app_fixture,admin_client
from io import BytesIO
import pytest


@pytest.fixture
def app(app_fixture): return app_fixture


def test_catalog_reuses_normalized_artist_and_album(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();songs=Track.query.filter_by(station_id=station.id).limit(2).all()
        if len(songs)==1:
            first=songs[0];copy=Track(station_id=station.id,uuid='10000000-0000-4000-8000-000000000001',title='Second',artist=' artist ',album=' album ',original_filename='two.mp3',storage_key='1'*32+'.mp3',media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256='1'*64);db.session.add(copy);songs.append(copy)
        songs[0].artist='Artist';songs[0].album='Album';organize_song(songs[0],{'track':'1/10','disc':'1','year':'2024','genre':'Pop','isrc':'abc123'})
        songs[1].artist=' artist ';songs[1].album=' album ';organize_song(songs[1],{'track':'2'});db.session.commit()
        assert songs[0].artist_id==songs[1].artist_id and songs[0].album_id==songs[1].album_id
        assert songs[0].track_number==1 and songs[0].release_year==2024 and songs[0].isrc=='ABC123'


def test_catalog_pages_and_bulk_categories_are_station_scoped(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();song=Track.query.filter_by(station_id=station.id).first();organize_song(song);category=MediaCategory.query.filter_by(station_id=station.id).first();db.session.commit();artist_id=song.artist_id;album_id=song.album_id;uuid=song.uuid;category_id=category.id
    client=admin_client(app);base='/admin/stations/test-station/media'
    assert client.get(base+'?view=artists').status_code==200
    assert client.get(f'{base}/artists/{artist_id}').status_code==200
    if album_id: assert client.get(f'{base}/albums/{album_id}').status_code==200
    assert client.get(f'/admin/stations/second-station/media/artists/{artist_id}').status_code==404
    assert client.post(base+'/bulk-categories',data={'csrf':'test-admin-csrf-token','track_uuid':uuid,'category_id':category_id,'operation':'assign'}).status_code==303
    assert client.post(base+'/bulk-categories',data={'csrf':'test-admin-csrf-token','track_uuid':uuid,'category_id':999999,'operation':'assign'}).status_code==404


def test_multi_file_upload_creates_independent_ingest_jobs(app,tmp_path):
    upload=tmp_path/'uploads';upload.mkdir();app.config['FREO_UPLOAD_ROOT']=str(upload)
    response=admin_client(app).post('/admin/stations/test-station/media/upload',data={'csrf':'test-admin-csrf-token','files':[(BytesIO(b'one'),'01-song.mp3'),(BytesIO(b'two'),'02-song.mp3')]},content_type='multipart/form-data')
    assert response.status_code==303
    with app.app_context():
        from app.models import MediaIngestJob
        jobs=MediaIngestJob.query.filter_by(kind='ingest').all();assert len(jobs)==2 and {j.original_filename for j in jobs}=={'01-song.mp3','02-song.mp3'}
