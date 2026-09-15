import os
import subprocess

import pytest

from app import create_app
from app.extensions import db
from app.models import Track
from app.services import media
from app.services.media_probe import MediaValidationError, probe
from app.services.media_storage import LocalMediaStorage
from app.services.stations import create_station


@pytest.fixture
def media_app(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    monkeypatch.setattr(media, 'require_admin', lambda: None)
    monkeypatch.setattr(media, 'PLAYLIST_ROOT', tmp_path / 'playlists')
    monkeypatch.setattr(os, 'chown', lambda *args: None)
    monkeypatch.setattr(media.grp if hasattr(media, 'grp') else __import__('grp'), 'getgrnam', lambda _: type('Group', (), {'gr_gid': os.getgid()})())
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        create_station('One', 'one')
        create_station('Two', 'two')
        yield app, LocalMediaStorage(tmp_path / 'media')
        db.drop_all()


def fixture_audio(tmp_path, frequency=997, title='Fixture'):
    path = tmp_path / f'fixture-{frequency}.mp3'
    subprocess.run(['/usr/bin/ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration=1', '-c:a', 'libmp3lame', '-metadata', f'title={title}', '-y', str(path)], check=True, timeout=15)
    return path


def test_ingest_duplicate_and_station_isolation(media_app, tmp_path):
    app, storage = media_app
    with app.app_context():
        source = fixture_audio(tmp_path)
        first, duplicate = media.ingest('one', source, storage=storage)
        assert not duplicate and first.title == 'Fixture'
        assert first.uuid != str(first.id)
        assert first.storage_key.startswith(first.uuid.replace('-', ''))
        assert media.verify(first, storage)
        same, duplicate = media.ingest('one', source, storage=storage)
        assert duplicate and same.id == first.id
        other, duplicate = media.ingest('two', source, storage=storage)
        assert not duplicate and other.id != first.id
        assert Track.query.count() == 2
        assert storage.regular_file('one', first.storage_key) != storage.regular_file('two', other.storage_key)
        client = app.test_client()
        listing = client.get('/api/stations/one/media').json['tracks']
        assert len(listing) == 1 and listing[0]['uuid'] == first.uuid
        assert client.get(f'/api/stations/two/media/{first.uuid}').status_code == 404
        assert client.post('/api/stations/one/media').status_code in (404, 405)
        body = client.get(f'/api/stations/one/media/{first.uuid}').get_data(as_text=True)
        assert str(storage.root) not in body and 'storage_key' not in body


@pytest.mark.parametrize('kind', ['music', 'imaging'])
def test_ingest_restores_group_read_with_private_staging_acl(media_app, tmp_path, kind):
    app, storage = media_app
    with app.app_context():
        _, staging = media._prepare_dirs(storage, 'one')
        # Reproduce web-preview ACL inheritance from a private staging folder.
        subprocess.run(['setfacl', '-m',
                        'd:u::rwx,d:u:65534:r--,d:g::---,d:m::r--,d:o::---',
                        str(staging)], check=True)
        source = fixture_audio(tmp_path)
        if kind == 'music':
            item, _ = media.ingest('one', source, storage=storage)
            path = storage.regular_file('one', item.storage_key)
        else:
            from app.services.imaging import ingest_imaging
            item, _ = ingest_imaging('one', source, asset_type='STATION_ID', storage=storage)
            path = storage.imaging_file('one', item.storage_key)
        acl = subprocess.check_output(['getfacl', '-cpn', str(path)], text=True)
        assert 'group::r--\n' in acl
        assert 'mask::r--\n' in acl
        assert 'user:65534:r--\n' in acl
        assert 'other::---\n' in acl
        assert staging.stat().st_mode & 0o777 == 0o700


def test_invalid_files_and_paths(media_app, tmp_path):
    app, storage = media_app
    with app.app_context():
        empty = tmp_path / 'empty.mp3'
        empty.touch()
        with pytest.raises(MediaValidationError):
            media.ingest('one', empty, storage=storage)
        bad = tmp_path / 'bad.mp3'
        bad.write_bytes(b'not audio')
        with pytest.raises(MediaValidationError):
            media.ingest('one', bad, storage=storage)
        link = tmp_path / 'link.mp3'
        link.symlink_to(bad)
        with pytest.raises(OSError):
            media.ingest('one', link, storage=storage)
        for key in ('../../etc/passwd', '/etc/passwd', 'file:///etc/passwd', 'a' * 32 + '.mp3/../x'):
            with pytest.raises(ValueError):
                storage.approved_path('one', key)
        with pytest.raises(ValueError):
            storage.approved_path('../two', 'a' * 32 + '.mp3')
        wav = tmp_path / 'unsupported.wav'
        subprocess.run(['/usr/bin/ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', '-y', str(wav)], check=True, timeout=15)
        with pytest.raises(MediaValidationError):
            media.ingest('one', wav, storage=storage)


def test_metadata_and_disabled_listing(media_app, tmp_path):
    app, storage = media_app
    with app.app_context():
        source = fixture_audio(tmp_path)
        track, _ = media.ingest('one', source, title='  Good\nTitle  ', artist='  Freo  ', storage=storage)
        assert track.title == 'GoodTitle' and track.artist == 'Freo'
        track.enabled = False
        db.session.commit()
        assert app.test_client().get('/api/stations/one/media?enabled=true').json['tracks'] == []
        assert len(app.test_client().get('/api/stations/one/media?enabled=false').json['tracks']) == 1
        storage.regular_file('one', track.storage_key).write_bytes(b'corrupted')
        with pytest.raises(MediaValidationError):
            media.verify(track, storage)


def test_probe_timeout_and_no_shell(monkeypatch):
    def timeout(args, **kwargs):
        assert args[0] == '/usr/bin/ffprobe' and kwargs.get('shell') is not True
        raise subprocess.TimeoutExpired(args, 1)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(MediaValidationError, match='Audio probe failed'):
        probe('/tmp/anything', timeout=1)


def test_import_metadata_is_atomic_and_duplicates_keep_existing_details(media_app,tmp_path):
    app,storage=media_app
    from app.models import MusicTag,Station
    with app.app_context():
        source=fixture_audio(tmp_path,frequency=640)
        foreign=MusicTag.query.filter_by(station_id=Station.query.filter_by(slug='two').one().id).first()
        with pytest.raises(ValueError):
            media.ingest('one',source,storage=storage,enabled=False,auto_enable_pending=True,
                         update_playlist=False,import_metadata={'title':'Invalid import','tags':[foreign.id]})
        assert Track.query.count()==0
        song,duplicate=media.ingest('one',source,storage=storage,enabled=False,auto_enable_pending=True,
                                    update_playlist=False,import_metadata={'title':'Chosen title','artist_name':'Chosen artist','album_name':'Chosen album'})
        assert not duplicate and song.title=='Chosen title' and song.artist=='Chosen artist' and song.album=='Chosen album'
        assert song.auto_enable_pending and not song.enabled
        same,duplicate=media.ingest('one',source,storage=storage,import_metadata={'title':'Overwrite'})
        assert duplicate and same.title=='Chosen title'
