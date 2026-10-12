"""Cold startup budgets and fail-closed lifecycle behavior; no live services."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import subprocess

import pytest

from freo_ops import engine_readiness as readiness, hosting, hosting_admin
from app import cli
from app.services import station_runtime
from tests.test_web import app


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0., sleeps=[])
    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds
    monkeypatch.setattr(readiness, 'time', SimpleNamespace(monotonic=lambda:state.now, sleep=sleep))
    return state


@pytest.mark.parametrize('ready_at', [75, 119])
def test_cold_start_can_finish_after_old_cli_and_hosted_deadlines(clock, ready_at):
    assert readiness.wait_ready(lambda:clock.now >= ready_at)
    assert clock.now == ready_at


def test_unready_engine_has_a_bounded_deadline(clock):
    assert not readiness.wait_ready(lambda:False)
    assert clock.now == readiness.STARTUP_TIMEOUT
    assert len(clock.sleeps) == readiness.STARTUP_TIMEOUT


def test_probe_failure_is_not_hidden_or_retried(clock):
    def failed():raise PermissionError('sandbox inaccessible')
    with pytest.raises(PermissionError):readiness.wait_ready(failed)
    assert not clock.sleeps


def test_station_cli_requires_real_stream_readiness_and_allows_cold_start(clock, monkeypatch):
    monkeypatch.setattr(cli, 'observed_status', lambda station:dict(playout='running',stream='online' if clock.now >= 80 else 'offline'))
    assert cli.wait_online(SimpleNamespace())
    assert clock.now == 80


def test_station_cli_does_not_accept_running_process_without_stream(clock, monkeypatch):
    monkeypatch.setattr(cli, 'observed_status', lambda station:dict(playout='running',stream='offline'))
    assert not cli.wait_online(SimpleNamespace())
    assert clock.now == readiness.STARTUP_TIMEOUT


def test_install_acceptance_allows_validation_then_cold_source_start(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    module = runpy.run_path(str(root/'scripts/accept-install.py'))
    elapsed = 2 * readiness.VALIDATION_TIMEOUT + 75 + 5
    def finished(args, **kwargs):
        if kwargs['timeout'] < elapsed:
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        return SimpleNamespace(returncode=0, stdout='station online')
    monkeypatch.setattr(module['subprocess'], 'run', finished)
    assert module['station']('create', 'fixture', '--start') == 'station online'


def test_audio_recovery_shares_cold_start_budget_and_honors_master_off(clock, monkeypatch):
    from app.extensions import db
    from app.routes import stations
    station=SimpleNamespace(desired_state='running')
    monkeypatch.setattr(db, 'session', SimpleNamespace(refresh=lambda item:None))
    monkeypatch.setattr(stations, 'observed_status', lambda item:dict(playout='running',stream='online' if clock.now>=85 else 'offline'))
    station_runtime.wait_audio_online(station)
    assert clock.now==85
    station.desired_state='stopped'
    with pytest.raises(RuntimeError,match='Master broadcast is OFF'):
        station_runtime.wait_audio_online(station)
    assert clock.now==85


@pytest.mark.parametrize('ready', [True, False])
def test_hosted_activation_waits_for_actual_readiness_and_keeps_failure_safe(app, tmp_path, monkeypatch, clock, ready):
    config=tmp_path/'hosting.json';config.write_text('{"hosted":false}')
    state=tmp_path/'state';state.mkdir()
    binary=tmp_path/'icecast';binary.write_bytes(b'freo-listeners')
    monkeypatch.setattr(hosting,'CONFIG',config)
    monkeypatch.setattr(hosting,'STATE',state)
    monkeypatch.setattr(hosting,'trusted',lambda path:None)
    monkeypatch.setattr(station_runtime,'operation_lock',nullcontext)
    monkeypatch.setattr(hosting_admin,'constraints',lambda policy:[])
    monkeypatch.setattr(hosting_admin,'provision_storage',lambda:set())
    from freo_ops import hosting_storage
    monkeypatch.setattr(hosting_storage,'locked',nullcontext)
    monkeypatch.setattr(hosting_admin,'active',lambda unit:False)
    monkeypatch.setattr(hosting_admin,'radio_policy',lambda policy:None)
    stops=[]
    monkeypatch.setattr(hosting_admin,'stop_broadcasts',lambda:stops.append(clock.now))
    monkeypatch.setattr(hosting_admin,'run',lambda args,**kwargs:f'{{ path={binary} ; }}')
    def verify(policy):
        if ready and clock.now >= 90:return dict(broadcasting=True,listeners=0)
        raise hosting.HostingError('verification_failed','A requested station has no Icecast source.')
    monkeypatch.setattr(hosting_admin,'verify',verify)
    requested=dict(hosted=True,plan='starter',status='active',limits=dict(hosting.PLANS['starter']))
    with app.app_context():
        if ready:
            result=hosting_admin.apply(requested,'configure')
            assert result['success'] and clock.now==90
            assert hosting.read()['status']=='active'
            assert not (state/'inhibit').exists()
        else:
            with pytest.raises(hosting.HostingError,match='no Icecast source'):
                hosting_admin.apply(requested,'configure')
            assert clock.now==readiness.STARTUP_TIMEOUT
            assert hosting.read()['status']=='maintenance'
            assert (state/'inhibit').exists()
            assert stops[-1]==readiness.STARTUP_TIMEOUT
            assert json.loads((state/'audit.jsonl').read_text())['result']['success'] is False


def test_radio_validation_timeout_retains_previous_configuration(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    module=runpy.run_path(str(root/'scripts/render-radio-config.py'))
    scope=module['main'].__globals__
    radio=tmp_path/'radio';radio.mkdir()
    secrets=tmp_path/'secrets';secrets.mkdir()
    keys=secrets/'engine.json'
    keys.write_text(json.dumps(dict(source='a'*64,relay='b'*64,admin='c'*64)));keys.chmod(0o600)
    original=(root/'deploy/icecast/icecast.xml.template').read_text()
    for key in ('SOURCE','RELAY','ADMIN'):original=original.replace('__'+key+'_PASSWORD__','a'*64)
    (radio/'icecast.xml').write_text(original)
    (radio/'freo-test.liq').write_text('previous validated diagnostic')
    scope.update(ROOT=tmp_path,RADIO=radio,SECRETS=secrets,KEYS=keys)
    monkeypatch.setattr(scope['os'],'geteuid',lambda:0)
    monkeypatch.setattr(scope['os'],'chown',lambda *args:None)
    monkeypatch.setattr(scope['pwd'],'getpwnam',lambda name:SimpleNamespace(pw_uid=0))
    monkeypatch.setattr(scope['grp'],'getgrnam',lambda name:SimpleNamespace(gr_gid=0))
    monkeypatch.setattr(hosting,'read',lambda:{'hosted':False})
    def fail(args,**kwargs):
        assert kwargs['timeout']==readiness.VALIDATION_TIMEOUT
        raise subprocess.TimeoutExpired(args,kwargs['timeout'])
    monkeypatch.setattr(scope['subprocess'],'run',fail)
    with pytest.raises(subprocess.TimeoutExpired):module['main']()
    assert (radio/'icecast.xml').read_text()==original
    assert (radio/'freo-test.liq').read_text()=='previous validated diagnostic'
    assert not list(radio.glob('.*'))
