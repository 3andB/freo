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


def test_standalone_guard_is_readable_after_private_umask_install(tmp_path,monkeypatch):
    source=Path(__file__).resolve().parents[1]/'scripts/install-hosting.py'
    (tmp_path/'usr/local/sbin').mkdir(parents=True)
    (tmp_path/'etc').mkdir()
    from freo_ops import hosting_recovery
    actual_path=Path
    monkeypatch.setattr(hosting_recovery,'Path',lambda name: tmp_path/str(name).lstrip('/') if str(name).startswith('/etc/') else actual_path(name))
    monkeypatch.setattr(h,'CONFIG',tmp_path/'etc/freo/hosting.json')
    monkeypatch.setattr(h,'STATE',tmp_path/'authority')
    monkeypatch.setattr(os,'geteuid',lambda:0)
    program=source.read_text()
    for name in ('/etc/freo','/usr/local/lib/freo-hosting','/usr/local/sbin/freo-admin'):
        program=program.replace(repr(name),repr(str(tmp_path/name.lstrip('/'))))
    previous=os.umask(0o077)
    try:exec(compile(program,str(source),'exec'),{'__file__':str(source),'__name__':'__main__'})
    finally:os.umask(previous)
    assert (tmp_path/'etc/freo').stat().st_mode & 0o777 == 0o755
    guard=tmp_path/'usr/local/lib/freo-hosting'
    assert guard.stat().st_mode & 0o777 == 0o755
    assert (guard/'freo_ops').stat().st_mode & 0o777 == 0o755
    for name in ('guard.py','freo_ops/hosting.py','freo_ops/__init__.py'):
        assert (guard/name).stat().st_mode & 0o004
    assert json.loads(h.CONFIG.read_text())=={'hosted':False}
    for unit in ('icecast2.service','freo-playout@.service','freo-mic.service','freo.service'):
        override=tmp_path/'etc/systemd/system'/(unit+'.d')/'hosting-authority.conf'
        assert 'ExecCondition=/usr/bin/python3 /usr/local/lib/freo-hosting/guard.py' in override.read_text()


@pytest.mark.skipif(os.geteuid()!=0, reason="Root-owned filesystem acceptance requires root")
def test_authority_markers_remain_visible_under_private_root_umask(tmp_path,monkeypatch):
    state=tmp_path/'authority'
    monkeypatch.setattr(h,'STATE',state)
    previous=os.umask(0o077)
    try:
        with h.administrative_lock():h.atomic(state/'inhibit',True)
    finally:os.umask(previous)
    assert state.stat().st_mode & 0o777 == 0o755
    assert (state/'inhibit').stat().st_mode & 0o777 == 0o644


def test_quota_access_survives_managed_production_path_reset(tmp_path,monkeypatch):
    from freo_ops import hosting_admin as admin
    actual=Path
    monkeypatch.setattr(admin,'Path',lambda name: tmp_path/str(name).lstrip('/') if str(name).startswith('/etc/') else actual(name))
    monkeypatch.setattr(admin,'run',lambda *args,**kwargs:'')
    root=tmp_path/'etc/systemd/system';root.mkdir(parents=True)
    directory=root/'freo-production.service.d';directory.mkdir()
    (directory/'storage.conf').write_text('[Service]\nReadWritePaths=\nReadWritePaths=/customer/uploads\n')
    assert 'freo-production.service' in admin.install_storage_access()
    paths=[]
    for path in sorted(directory.glob('*.conf')):
        for line in path.read_text().splitlines():
            if line.startswith('ReadWritePaths='):
                value=line.split('=',1)[1]
                if not value:paths=[]
                else:paths.extend(value.split())
    assert '/customer/uploads' in paths and str(storage.ROOT) in paths
    assert not admin.install_storage_access(), 'repeated activation must not restart unchanged workers'


def test_verification_rejects_readonly_running_worker(monkeypatch):
    from freo_ops import hosting_admin as admin
    from types import SimpleNamespace
    monkeypatch.setattr(admin,'run',lambda *args,**kwargs:'123')
    monkeypatch.setattr(admin.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    with pytest.raises(h.HostingError) as error:admin.verify_storage_access('freo-production.service','freo-ingest')
    assert error.value.code=='verification_failed'
    assert error.value.details['unit']=='freo-production.service'
