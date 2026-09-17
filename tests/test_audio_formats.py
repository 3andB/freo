"""Decode real files through ingest, private previews and Liquidsoap."""
import json
import subprocess

import pytest
from app.extensions import db
from app.models import AdminUser, Station, Track
from app.services import media
from app.services.media_probe import probe, MediaValidationError
from app.services.music_delete import delete_audio
from tests.test_media import media_app
from tests.test_web import admin_client

FORMATS = [('mp3', 'libmp3lame'), ('wav', 'pcm_s16le'), ('wav', 'pcm_s24le'),
           ('wav', 'pcm_f32le'), ('m4a', 'aac'), ('m4a', 'alac'), ('flac', 'flac')]


def audio_file(tmp_path, extension, codec):
    path = tmp_path / f'{codec}.{extension}'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=523:duration=2',
                    '-c:a', codec, '-metadata', 'title=Format proof', '-metadata', 'artist=Freo test',
                    '-metadata', 'album=Format album', '-y', str(path)], check=True, timeout=15)
    return path


@pytest.mark.parametrize('extension,codec', FORMATS)
def test_formats_ingest_preview_and_delete(media_app, tmp_path, monkeypatch, extension, codec):
    app, storage = media_app
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(storage.root))
    with app.app_context():
        db.session.add(AdminUser(email='admin@example.test', password_hash='unused'));db.session.commit()
        source = audio_file(tmp_path, extension, codec)
        song, duplicate = media.ingest('one', source, storage=storage)
        assert not duplicate and song.media_type == extension
        assert song.title == 'Format proof' and song.artist == 'Freo test' and song.album == 'Format album'
        assert storage.regular_file('one', song.storage_key).read_bytes() == source.read_bytes()
        assert (song.preview_key is not None) == (extension != 'mp3')
        if song.preview_key:
            preview = storage.preview_file('one', song.preview_key)
            assert probe(preview)['media_type'] == 'mp3'
        client = admin_client(app)
        url = f'/admin/stations/one/media/{song.uuid}/audition'
        assert app.test_client().get(url).status_code == 302
        response = client.get(url, headers={'Range': 'bytes=0-63'})
        assert response.status_code == 206 and response.mimetype == 'audio/mpeg' and len(response.data) == 64
        assert client.get(url.replace('/one/', '/two/')).status_code == 404
        assert client.get('/admin/stations/one/media?format=' + extension).status_code == 200
        same, duplicate = media.ingest('one', source, storage=storage)
        assert duplicate and same.id == song.id
        original = storage.regular_file('one', song.storage_key)
        delete_audio(song)
        assert not original.exists() and (not song.preview_key)
        if extension != 'mp3': assert not preview.exists()


def test_preview_failure_cleans_up_and_rejects_import(media_app, tmp_path, monkeypatch):
    app, storage = media_app
    from app.services import media_preview
    def fail(source, target):
        target.write_bytes(b'partial')
        raise MediaValidationError('Decode failed')
    monkeypatch.setattr(media_preview, 'create_preview', fail)
    with app.app_context():
        source = audio_file(tmp_path, 'flac', 'flac')
        with pytest.raises(MediaValidationError): media.ingest('one', source, storage=storage)
        assert Track.query.count() == 0
        assert list((storage.station_dir('one') / 'previews').iterdir()) == []
        assert list((storage.station_dir('one') / 'originals').iterdir()) == []


def test_liquidsoap_decodes_all_formats(tmp_path):
    lines = ['settings.init.allow_root := true', 'settings.log.level := 2', 'done = ref(0)',
             f'def finished() done := done() + 1; if done() == {len(FORMATS)} then shutdown() end end']
    for index, (extension, codec) in enumerate(FORMATS):
        source = audio_file(tmp_path, extension, codec)
        target = tmp_path / f'decoded-{index}.wav'
        lines.append(f's{index} = request.once(request.create({json.dumps(str(source))}))')
        lines.append(f'output.file(%wav, {json.dumps(str(target))}, fallible=true, on_stop=finished, s{index})')
    script = tmp_path / 'formats.liq';script.write_text('\n'.join(lines))
    result = subprocess.run(['liquidsoap', str(script)], capture_output=True, text=True, timeout=75)
    assert result.returncode == 0, result.stdout + result.stderr
    for index in range(len(FORMATS)):
        target = tmp_path / f'decoded-{index}.wav'
        assert target.stat().st_size > 100000 and probe(target)['duration_ms'] >= 1800
