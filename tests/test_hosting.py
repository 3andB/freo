"""Hosting boundaries; installed audio acceptance lives in hosting_acceptance/."""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import pytest
from freo_ops import hosting as h, hosting_storage as storage


@pytest.fixture
def policy(tmp_path, monkeypatch):
    config=tmp_path/'hosting.json';state=tmp_path/'authority';state.mkdir()
    monkeypatch.setattr(h,'CONFIG',config);monkeypatch.setattr(h,'STATE',state)
    # Unit fixture directory is under pytest's /tmp, unlike the root-owned host.
    monkeypatch.setattr(h,'trusted',lambda p: None)
    h.atomic(config,dict(hosted=True,plan='starter',status='active',limits=dict(h.PLANS['starter'])))
    return config


@pytest.mark.parametrize('value',[{}, {'hosted':1},{'hosted':False,'plan':'starter'}, {'hosted':True,'plan':'unknown','status':'active','limits':h.PLANS['starter']}])
def test_strict_schema(value):
    with pytest.raises(h.HostingError):h.validate(value)


@pytest.mark.parametrize('value',[True,0,-1,1.5,'25',1_000_001])
def test_integer_limits(policy,value):
    data=h.read();data['limits']['storage_gb']=value
    with pytest.raises(h.HostingError):h.validate(data)


def test_missing_and_disabled_after_enabling_fail_closed(policy):
    h.atomic(h.STATE/'enabled',True);policy.unlink()
    with pytest.raises(h.HostingError):h.read()
    h.atomic(policy,{'hosted':False})
    with pytest.raises(h.HostingError):h.read()


def test_legacy_self_hosting(policy):
    policy.unlink();assert h.read()=={'hosted':False}
    h.check_bitrate(999999);h.check_stations(999999)
    h.atomic(policy,{'hosted':False});assert h.require_service()=={'hosted':False}


def test_duplicate_json_fields(policy):
    policy.write_text('{"hosted":false,"hosted":true}')
    with pytest.raises(h.HostingError):h.read()


@pytest.mark.parametrize('status,allowed',[('active',True),('past_due',True),('suspended',False),('maintenance',False)])
def test_service_states(policy,status,allowed):
    data=h.read();data['status']=status;h.atomic(policy,data)
    if allowed:assert h.require_service()['status']==status
    else:
        with pytest.raises(h.HostingError):h.require_service()


def test_limits_are_authoritative(policy):
    data=h.read();data['limits'].update(stations=7,bitrate_kbps=192);h.atomic(policy,data)
    h.check_stations(6,adding=True);h.check_bitrate(192)
    with pytest.raises(h.HostingError) as error:h.check_stations(7,adding=True)
    assert error.value.response()['current_stations']==7
    with pytest.raises(h.HostingError):h.check_bitrate(256)


@pytest.fixture
def quota(policy,tmp_path,monkeypatch):
    root=tmp_path/'ledger';root.mkdir();(root/'lock').touch()
    media=tmp_path/'media';media.mkdir()
    monkeypatch.setattr(storage,'ROOT',root)
    monkeypatch.setattr(storage,'inventory',lambda:dict(roots=[str(media)]))
    monkeypatch.setattr(storage,'blob_usage',lambda config:0)
    data=h.read();data['limits']['storage_gb']=1;h.atomic(policy,data)
    return media


def test_hardlinks_count_once_and_existing_media(quota):
    (quota/'a').write_bytes(b'1234');os.link(quota/'a',quota/'b')
    assert storage.usage()['used_bytes']==4
    (quota/'link').symlink_to('/etc/passwd')
    with pytest.raises(h.HostingError):storage.usage()


def test_over_quota_cleanup_and_no_growth(quota):
    with (quota/'large').open('wb') as stream:stream.truncate(1_000_000_001)
    assert storage.usage()['over_quota']
    with pytest.raises(h.HostingError),storage.reserve(1):pass
    (quota/'large').unlink()
    with storage.reserve(1):pass


def test_concurrent_reservations_cannot_exceed_quota(quota):
    ctx=multiprocessing.get_context('fork');ready=ctx.Event();release=ctx.Event();queue=ctx.Queue()
    def holder():
        with storage.reserve(600_000_000):
            ready.set();release.wait(10)
    process=ctx.Process(target=holder);process.start();assert ready.wait(10)
    try:
        with pytest.raises(h.HostingError),storage.reserve(500_000_000):pass
        assert storage.usage()['reserved_bytes']==600_000_000
    finally:
        release.set();process.join(10)
    assert process.exitcode==0
    with storage.reserve(1_000_000_000):pass


def test_crashed_reservation_reclaimed_files_retained(quota):
    ctx=multiprocessing.get_context('fork')
    def crash():
        with storage.reserve(1000):
            (quota/'partial').write_bytes(b'123')
            os._exit(1)
    process=ctx.Process(target=crash);process.start();process.join(10)
    assert storage.usage()['reserved_bytes']==0
    assert storage.usage()['used_bytes']==3


def test_failed_writer_releases_reservation(quota):
    with pytest.raises(RuntimeError),storage.reserve(100):raise RuntimeError()
    assert storage.usage()['reserved_bytes']==0


def test_kernel_subprocess_output_cap(quota):
    output=quota/'output'
    result=storage.run_media(['/usr/bin/python3','-c','import sys;open(sys.argv[1],"wb").write(b"x"*10000)',str(output)],max_output_bytes=1024,capture_output=True)
    assert result.returncode!=0
    assert output.stat().st_size<=1024


def test_station_and_bitrate_backend(policy,monkeypatch):
    monkeypatch.setenv('DATABASE_URL','sqlite:///:memory:');monkeypatch.setenv('SECRET_KEY','hosting-test')
    from app import create_app
    from app.extensions import db
    from app.services.stations import create_station
    from app.models import StreamMount
    app=create_app('testing')
    with app.app_context():
        db.create_all()
        for n in range(3):assert create_station(str(n),'station-'+str(n)).stream.bitrate==128
        with pytest.raises(h.HostingError):create_station('fourth','fourth')
        db.session.rollback()
        stream=StreamMount.query.first();stream.bitrate=192
        with pytest.raises(h.HostingError):db.session.commit()
        db.session.rollback();db.drop_all()


def test_radio_limit_is_server_wide(policy):
    import xml.etree.ElementTree as ET
    from freo_ops.hosting_admin import render_listener_limit
    root=ET.fromstring('<icecast><limits><clients>100</clients></limits><mount><mount-name>/one</mount-name></mount><mount><mount-name>/two</mount-name></mount></icecast>')
    render_listener_limit(root)
    assert root.findtext('limits/freo-listeners')=='100'
    assert int(root.findtext('limits/clients'))>100
    assert not root.findall('mount/max-listeners')


def test_admin_repair_never_defaults_to_active_or_self_hosted(policy):
    from freo_ops.hosting_admin import administrative_policy
    saved=h.read();h.atomic(h.STATE/'last-valid.json',saved)
    h.atomic(h.STATE/'enabled',True);policy.write_text('invalid')
    with pytest.raises(h.HostingError):administrative_policy()
    restored=administrative_policy(repair=True)
    assert restored['hosted'] and restored['status']=='maintenance'
    assert restored['limits']==saved['limits']


def test_native_listener_limit_rejects_unsupported_capacity(policy):
    data=h.read();data['limits']['listeners']=32641
    with pytest.raises(h.HostingError):h.validate(data)


def test_blob_reservation_lives_until_outer_transaction_commit(policy,monkeypatch):
    from contextlib import contextmanager
    live=[]
    @contextmanager
    def reserve(size):
        live.append(size)
        try:yield
        finally:live.remove(size)
    monkeypatch.setattr(storage,'reserve',reserve)
    monkeypatch.setenv('DATABASE_URL','sqlite:///:memory:');monkeypatch.setenv('SECRET_KEY','hosting-test')
    from app import create_app
    from app.extensions import db
    from app.models import WebsiteAsset
    app=create_app('testing')
    with app.app_context():
        db.create_all()
        with db.session.begin_nested():
            db.session.add(WebsiteAsset(id='hosting-test',image=b'1234',small=b'12'))
            db.session.flush()
        assert live==[6], 'savepoint commit must retain the quota reservation'
        db.session.commit()
        assert live==[]
        db.drop_all()


def test_encoder_retains_reservation_after_parent_is_killed(quota):
    import signal,time
    ctx=multiprocessing.get_context('fork')
    ready=quota/'ready';finished=quota/'finished'
    def encode():
        storage.run_media(['/usr/bin/python3','-c',
            'import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text("ready");time.sleep(2);Path(sys.argv[2]).write_text("finished")',
            str(ready),str(finished)],max_output_bytes=600_000_000,check=True)
    process=ctx.Process(target=encode);process.start()
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
        assert ready.exists()
        os.kill(process.pid,signal.SIGKILL);process.join(5)
        with pytest.raises(h.HostingError),storage.reserve(500_000_000):pass
        deadline=time.monotonic()+10
        while not finished.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert finished.exists()
        # Allow the encoder to close its inherited descriptor after the write.
        deadline=time.monotonic()+5
        while storage.usage()['reserved_bytes'] and time.monotonic()<deadline:time.sleep(.05)
        assert storage.usage()['reserved_bytes']==0
    finally:
        if process.is_alive():process.kill();process.join(5)
