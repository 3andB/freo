import json
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from app.extensions import db
from app.models import AdminUser, Station
from app.services import station_audio as audio, station_runtime as runtime
from tests.test_web import app, admin_client

BASE = '/admin/stations/test-station/settings/audio'
CSRF = {'csrf': 'test-admin-csrf-token'}


def test_audio_settings_permissions_validation_and_queue(app, monkeypatch):
    client = admin_client(app)
    assert app.test_client().get(BASE).status_code == 302
    assert client.post(BASE, data={}).status_code == 400
    before = client.get(BASE).json
    assert before['active']['bitrate'] == 64 and not before['active']['agc']
    for bitrate, bass in [('192','0'), ('96','nan'), ('96','7'), ('96','inf')]:
        client.post(BASE, data=dict(CSRF, bitrate=bitrate, bass=bass, revision=1))
        assert client.get(BASE).json == before
    client.post(BASE, data=dict(CSRF, bitrate=128, bass=2, agc='yes', eq='yes', multiband='yes', revision=1))
    queued = client.get(BASE).json
    assert queued['status'] == 'pending' and queued['active']['bitrate'] == 64 and queued['pending']['bitrate'] == 128
    client.post(BASE, data=dict(CSRF, bitrate=96, revision=queued['revision']))
    assert client.get(BASE).json == queued
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        monkeypatch.setattr(runtime, 'ROOT', __import__('pathlib').Path(app.instance_path))
        # These tests exercise durable state separately from real runtime file tests.
        from contextlib import nullcontext
        monkeypatch.setattr(runtime, 'operation_lock', nullcontext)
        monkeypatch.setattr(runtime, 'require_root', lambda: None)
        apply = Mock();monkeypatch.setattr(runtime, 'apply_audio', apply)
        monkeypatch.setattr(runtime, 'finish_audio', Mock())
        audio.process_audio(station)
        assert station.stream.bitrate == 128 and station.stream.audio_processing['eq']
        assert station.stream.audio_status == 'ready' and station.stream.pending_audio is None
        assert Station.query.filter_by(slug='second-station').one().stream.bitrate == 64
    client.post(BASE, data=dict(CSRF, bitrate=96, revision=1))
    assert client.get(BASE).json['active']['bitrate'] == 128
    assert client.get(BASE).json['status'] == 'ready'


@pytest.fixture
def audio_runtime(app, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'ROOT', tmp_path)
    monkeypatch.setattr(runtime, 'CONFIGS', tmp_path)
    monkeypatch.setattr(runtime, 'credential', lambda slug: 'a' * 64)
    monkeypatch.setattr(runtime.os, 'chown', lambda *args: None)
    monkeypatch.setattr(runtime, 'run_checked', Mock())
    monkeypatch.setattr(runtime, 'service_action', Mock(return_value=True))
    monkeypatch.setattr(runtime, 'wait_audio_online', Mock())
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        target = tmp_path / 'test-station.liq';target.write_text('prior configuration')
        (tmp_path / 'second-station.liq').write_text('unaffected station')
        yield station, target


def queue(station):
    audio.queue_settings(station, dict(bitrate=96, agc=True), station.stream.audio_revision, AdminUser.query.first())
    db.session.commit()


def test_apply_restarts_only_target_and_records_active_settings(audio_runtime):
    station, target = audio_runtime
    queue(station);audio.process_audio(station)
    assert '%mp3(bitrate=96)' in target.read_text()
    assert station.stream.bitrate == 96 and station.stream.audio_status == 'ready'
    assert target.with_name('second-station.liq').read_text() == 'unaffected station'
    assert all(call.args[0] == 'test-station' for call in runtime.service_action.call_args_list)
    assert not runtime.audio_backup(station).exists()


def test_restart_failure_restores_config_and_keeps_active_values(audio_runtime, monkeypatch):
    station, target = audio_runtime
    queue(station)
    monkeypatch.setattr(runtime, 'wait_audio_online', Mock(side_effect=[RuntimeError('failed candidate'), None]))
    with pytest.raises(RuntimeError): audio.process_audio(station)
    assert target.read_text() == 'prior configuration'
    assert station.stream.bitrate == 64 and station.stream.audio_status == 'failed'
    assert station.stream.pending_audio['bitrate'] == 96
    assert runtime.service_action.call_args_list.count(__import__('unittest.mock', fromlist=['call']).call('test-station','restart')) == 2


def test_invalid_config_never_restarts_station(audio_runtime, monkeypatch):
    station, target = audio_runtime
    queue(station)
    monkeypatch.setattr(runtime, 'run_checked', Mock(side_effect=RuntimeError('invalid config')))
    with pytest.raises(RuntimeError): audio.process_audio(station)
    assert target.read_text() == 'prior configuration'
    runtime.service_action.assert_not_called()


def test_stopped_station_stays_stopped(audio_runtime, monkeypatch):
    station, target = audio_runtime
    station.desired_state = 'stopped';db.session.commit()
    monkeypatch.setattr(runtime, 'service_action', Mock(return_value=False))
    queue(station);audio.process_audio(station)
    assert station.stream.bitrate == 96
    assert not any(c.args[1] in ('start', 'restart') for c in runtime.service_action.call_args_list)


def test_interrupted_apply_keeps_original_backup(audio_runtime, monkeypatch):
    station, target = audio_runtime
    queue(station)
    runtime.audio_backup(station).write_text('before interruption')
    target.write_text('candidate left by interrupted worker')
    station.stream.audio_status = 'applying';db.session.commit()
    monkeypatch.setattr(runtime, 'wait_audio_online', Mock(side_effect=[RuntimeError('candidate failed'), None]))
    with pytest.raises(RuntimeError): audio.process_audio(station)
    assert target.read_text() == 'before interruption'


def test_notice_once_per_user_per_utc_day_across_stations(app):
    client = admin_client(app)
    url = '/admin/stations/test-station/media/import-notice'
    assert app.test_client().post(url, data=CSRF).status_code == 302
    assert client.post(url, data={}).status_code == 400
    assert client.post(url, data=CSRF).json == {'show': True}
    assert admin_client(app).post(url.replace('test-station','second-station'), data=CSRF).json == {'show': False}
    with app.app_context():
        AdminUser.query.first().import_notice_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        db.session.commit()
    assert client.post(url, data=CSRF).json == {'show': True}
    with app.app_context():
        user=AdminUser(email='other@example.test',password_hash='unused');db.session.add(user);db.session.commit();identifier=user.id
    other=app.test_client()
    with other.session_transaction() as session:
        session['admin_user_id']=identifier;session['admin_csrf']=CSRF['csrf']
    assert other.post(url, data=CSRF).json == {'show': True}


def test_real_processing_and_bitrates(tmp_path):
    # One engine writes all three encoders. Inspect actual MPEG headers and PCM.
    values=dict(bitrate=128, agc=True, multiband=True, eq=True, bass=2.0, mid=-1.0, treble=1.0)
    script = tmp_path / 'processing.liq'
    lines=['settings.init.allow_root := true', 'settings.log.level := 2',
           'radio = sine(amplitude=0.8, 523.0)', audio.processing_liquidsoap(values),
           'radio = limit(attack=1.0, release=100.0, threshold=-1.5, ratio=100.0, gain=0.0, radio)']
    for rate in audio.BITRATES:
        lines.append(f'output.file(%mp3(bitrate={rate}), {json.dumps(str(tmp_path / (str(rate)+".mp3")))}, radio)')
    lines += [f'output.file(%wav, {json.dumps(str(tmp_path / "processed.wav"))}, radio)',
              'thread.run(delay=5.0, fun () -> shutdown())']
    script.write_text('\n'.join(lines))
    result=subprocess.run(['liquidsoap',str(script)],capture_output=True,text=True,timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    for rate in audio.BITRATES:
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=bit_rate','-of','json',str(tmp_path / (str(rate)+'.mp3'))]))
        assert int(info['streams'][0]['bit_rate']) == rate*1000
    from tests.test_loudness_playout import measure
    levels=measure(tmp_path / 'processed.wav')
    assert -30 < float(levels['input_i']) < -5 and float(levels['input_tp']) < 0


def test_full_station_template_with_processing(app, tmp_path):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        text=runtime.render_liquidsoap(station, 'a'*64, dict(bitrate=128, agc=True, eq=True, bass=6, mid=-6, treble=6, multiband=True))
    script=tmp_path/'station.liq';script.write_text(text)
    result=subprocess.run(['liquidsoap','--check',str(script)],capture_output=True,text=True,timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_audio_migration_roundtrip_preserves_existing_data(app):
    runner=app.test_cli_runner()
    for args in [('db','stamp','c84a2e019b36'),('db','downgrade','b185c9a027d6'),('db','upgrade','c84a2e019b36')]:
        result=runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.remove()
        station=Station.query.filter_by(slug='test-station').one()
        assert station.stream.bitrate == 64 and station.stream.audio_status == 'ready'
        assert not station.stream.audio_processing and station.stream.audio_revision == 1
        assert AdminUser.query.first().import_notice_date is None
        station.stream.bitrate=96;db.session.commit()
    result=runner.invoke(args=['db','downgrade','b185c9a027d6'])
    assert result.exit_code != 0
    with app.app_context():
        db.session.remove()
        assert Station.query.filter_by(slug='test-station').one().stream.bitrate == 96
