"""Administrative boundary and interruption regressions; no live host mutations."""
import json
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
import pytest
from freo_ops import admin as a, admin_backup as b, admin_upgrade as u, hosting as h


@pytest.fixture
def state(tmp_path,monkeypatch):
    root=tmp_path/'admin';root.mkdir(mode=0o700)
    monkeypatch.setattr(a,'STATE',root)
    monkeypatch.setattr(h,'trusted',lambda path:None)
    monkeypatch.setattr(a,'private_directory',lambda path: (path.mkdir(parents=True,exist_ok=True) or path))
    monkeypatch.setattr(h,'administrative_lock',lambda:nullcontext())
    a.write(root/'identity.json',dict(installation_id='0919533f-7811-45f2-ba08-5648daa930c9'))
    monkeypatch.setattr(a,'UPDATES',tmp_path/'updates')
    return root


@pytest.mark.parametrize('argv',[
    ['services','restart','--service','postgresql'],['services','restart','--service','icecast;id'],
    ['upgrade','apply','--url','https://example.invalid'],['backup','restore','--id','abc'],
    ['status','--env-file','/tmp/test'],['backup','delete','--id','abc'],
    ['upgrade','apply','--ver','1.0.0'],['services','restart','--service','freo.service'],
])
def test_reject_unapproved_interfaces(argv,state,capsys):
    assert a.main(argv)==2
    result=json.loads(capsys.readouterr().out)
    assert result['schema_version']==1 and not result['success']


def test_unprivileged_cannot_read_or_mutate(state,monkeypatch,capsys):
    monkeypatch.setattr(a.os,'geteuid',lambda:1000)
    assert a.main(['status'])==3
    assert json.loads(capsys.readouterr().out)['error']=='unauthorized'


@pytest.mark.parametrize('value',['../key','/etc/passwd','A'*32,'a'*31,'a'*33,'abc\x00'])
def test_backup_ids_do_not_resolve_paths(value):
    with pytest.raises(h.HostingError):b.identifier(value)


def test_lost_key_never_silently_replaced(state):
    original=a.key()
    assert a.key()==original
    (state/'backup.key').unlink()
    with pytest.raises(h.HostingError,match='escrowed'):a.key()
    assert not (state/'backup.key').exists()


def test_replaced_key_rejected(state):
    a.key();(state/'backup.key').write_bytes(b'different')
    with pytest.raises(h.HostingError,match='identity'):a.key()


def test_live_restore_needs_destination_confirmation(state):
    with pytest.raises(h.HostingError) as error:
        b.restore_start(SimpleNamespace(confirm_installation='wrong',id='a'*32))
    assert error.value.code=='confirmation_required'
    assert not (state/'operation.json').exists()


def test_corrupt_bundle_rejected_before_decryption(state,monkeypatch):
    directory=state/'backups'/('a'*32);directory.mkdir(parents=True)
    (directory/'bundle.gpg').write_bytes(b'corrupt')
    a.write(directory/'metadata.json',dict(id='a'*32,sha256='wrong'))
    monkeypatch.setattr(a,'key',lambda:pytest.fail('must not decrypt a mismatched bundle'))
    with pytest.raises(h.HostingError) as error:b.verify('a'*32)
    assert error.value.code=='backup_integrity_failed'


def test_pending_operation_blocks_new_mutation(state):
    a.write(state/'operation.json',dict(operation_id='a'*32,operation='backup.restore',phase='attaching'))
    with pytest.raises(h.HostingError) as error:a.begin('backup.create')
    assert error.value.code=='recovery_required'


def test_unfinished_upgrade_blocks_service_start(state):
    a.UPDATES.mkdir()
    a.write(a.UPDATES/'journal.json',dict(operation='b'*32,phase='migration'))
    with pytest.raises(h.HostingError):a.begin('services.recover')


def test_service_recovery_cannot_restore_database_implicitly(state,monkeypatch):
    a.UPDATES.mkdir()
    a.write(a.UPDATES/'journal.json',dict(phase='migration'))
    monkeypatch.setattr(u,'register_backup',lambda value:None)
    with pytest.raises(h.HostingError) as error:b.resume(dict(operation='upgrade.apply',backup_id='a'*32))
    assert error.value.code=='recovery_required'
    assert error.value.details['backup_id']=='a'*32


def test_hosted_suspension_prevents_restart(state,monkeypatch):
    policy=dict(hosted=True,status='suspended')
    monkeypatch.setattr(h,'read',lambda:policy)
    monkeypatch.setattr(a,'run',lambda *args,**kwargs:pytest.fail('systemctl must not run'))
    with pytest.raises(h.HostingError) as error:
        a.service_action(SimpleNamespace(action='restart',service='icecast'))
    assert error.value.code=='service_inhibited'


@pytest.mark.parametrize('version',['../version','latest','1.0.0;id','https://example.invalid'])
def test_upgrade_does_not_accept_paths_or_urls(version):
    with pytest.raises(h.HostingError) as error:u.staged(version)
    assert error.value.code=='invalid_arguments'


def test_errors_do_not_expose_subprocess_secrets(state,monkeypatch,capsys):
    monkeypatch.setattr(a,'status',lambda:(_ for _ in ()).throw(RuntimeError('postgresql://secret:password@localhost')))
    assert a.main(['status'])==6
    output=capsys.readouterr().out
    assert 'password' not in output and 'postgresql' not in output
    assert json.loads(output)['success'] is False


def test_selfhost_inhibition_ignores_stale_hosting_marker(state):
    h.STATE.mkdir();(h.STATE/'inhibit').touch()
    assert a.inhibited({'hosted':False}) is False


def test_restore_dispatch_resumes_only_matching_authorization(state,monkeypatch):
    operation=dict(operation_id='a'*32,operation='backup.restore',phase='attaching',restore_id='b'*32)
    a.write(state/'operation.json',operation)
    monkeypatch.setattr(b,'record',lambda value:({'installation_id':'0919533f-7811-45f2-ba08-5648daa930c9'},Path('/bundle')))
    monkeypatch.setattr(b,'verify',lambda value:None)
    monkeypatch.setattr(b,'local_database',lambda:None)
    monkeypatch.setattr(b,'disk_check',lambda paths,**kwargs:None)
    monkeypatch.setattr(b,'backup_space',lambda metadata:0)
    monkeypatch.setattr(b,'roots',lambda:[])
    with pytest.raises(h.HostingError) as error:
        b.restore_start(SimpleNamespace(confirm_installation='0919533f-7811-45f2-ba08-5648daa930c9',id='c'*32))
    assert error.value.code=='recovery_required'


def test_destination_trust_and_selfhost_policy_survive_attachment(state,monkeypatch):
    config=state/'etc';config.mkdir()
    original_path=Path
    def mapped(value):
        value=str(value)
        return config/original_path(value).name if value.startswith('/etc/freo/') else original_path(value)
    monkeypatch.setattr(b,'Path',mapped)
    (config/'hosting.json').write_text('{"hosted":false}')
    (config/'publisher.gpg').write_bytes(b'trusted publisher')
    operation={}
    with b.administrative_authority(operation):
        (config/'hosting.json').write_text('{"hosted":true}')
        (config/'publisher.gpg').write_bytes(b'old backup publisher')
        (config/'admin-upgrades.json').write_text('{"allow_candidate":true}')
    assert json.loads((config/'hosting.json').read_text())=={'hosted':False}
    assert (config/'publisher.gpg').read_bytes()==b'trusted publisher'
    assert not (config/'admin-upgrades.json').exists()
    # A repeated recovery uses the original write-ahead authority, not damaged files.
    (config/'hosting.json').write_text('{"hosted":true}')
    with b.administrative_authority(operation):
        assert json.loads((config/'hosting.json').read_text())=={'hosted':False}


def test_database_attachment_preflight_closes_its_own_session(monkeypatch):
    class Connection:
        closed=False
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,*args):pass
        def fetchone(self):return (0,)
        def close(self):self.closed=True
    connection=Connection()
    monkeypatch.setattr(b.recovery,'connect',lambda url:connection)
    b.ensure_no_clients('private fixture')
    assert connection.closed


def test_direct_installation_restores_to_canonical_deployment(state,monkeypatch):
    etc=state/'etc';etc.mkdir()
    units=state/'systemd';units.mkdir()
    release=state/'release';release.mkdir()
    (release/'.env').write_text('DATABASE_URL=private-fixture')
    unit=units/'freo.service'
    unit.write_text('[Service]\nWorkingDirectory=/opt/freo\nEnvironmentFile=/opt/freo/.env\nExecStart=/opt/freo/venv/bin/gunicorn wsgi:app\n')
    original=Path
    mapped={'/etc/freo/freo.env':etc/'freo.env','/etc/systemd/system':units}
    monkeypatch.setattr(b,'Path',lambda value:mapped.get(str(value),original(value)))
    b.adopt_restored_release(dict(source='/opt/freo',env_file='/opt/freo/.env'),release)
    assert (etc/'freo.env').read_text()=='DATABASE_URL=private-fixture'
    assert 'WorkingDirectory=/opt/freo/current' in unit.read_text()
    assert 'EnvironmentFile=/etc/freo/freo.env' in unit.read_text()
    assert 'ExecStart=/opt/freo/current/venv/bin/gunicorn' in unit.read_text()


def test_upgrade_check_reports_cached_older_versions_without_running_downgrade(state,monkeypatch):
    staged=a.UPDATES/'staged'/'0.3.2';staged.mkdir(parents=True)
    monkeypatch.setattr(u,'verify_staged',lambda version:dict(version=version,compatible=False))
    monkeypatch.setattr(u,'staged',lambda version:pytest.fail('incompatible version must not run updater'))
    result=u.dispatch(SimpleNamespace(action='check'))
    assert result['releases']==[dict(version='0.3.2',compatible=False,preflight='incompatible')]


@pytest.mark.parametrize('current',[False,True])
def test_upgrade_check_cleanup_never_removes_current_release(state,monkeypatch,current):
    from freo_ops import upgrade
    directory=a.UPDATES/'staged'/'1.0.0';directory.mkdir(parents=True)
    releases=state/'releases';releases.mkdir()
    installed=releases/('a'*32);installed.mkdir();(installed/'keep').touch()
    copied=installed if current else releases/('b'*32)
    copied.mkdir(exist_ok=True)
    (copied/'release.json').write_text('{}')
    original=Path
    monkeypatch.setattr(u,'Path',lambda value:releases if str(value)=='/opt/freo/releases' else original(value))
    monkeypatch.setattr(a,'source',lambda:installed)
    monkeypatch.setattr(a,'settings',lambda:(state/'env',{}))
    monkeypatch.setattr(u,'verify_staged',lambda version:dict(version=version,compatible=True))
    monkeypatch.setattr(u,'staged',lambda version:('artifact','signature','keyring'))
    monkeypatch.setattr(u,'candidate_allowed',lambda:False)
    def checked(*args,**kwargs):
        assert kwargs['check'] is True
        a.write(a.UPDATES/'journal.json',dict(release=str(copied),operation=copied.name,phase='preflight_passed'))
        return dict(status='preflight_passed')
    monkeypatch.setattr(upgrade,'upgrade',checked)
    u.dispatch(SimpleNamespace(action='check'))
    assert installed.is_dir() and (installed/'keep').exists()
    assert copied.exists()==current


def test_backup_expansion_budget_uses_recorded_uncompressed_size(state,monkeypatch):
    monkeypatch.setattr(b.shutil,'disk_usage',lambda path:SimpleNamespace(free=2_000_000_000))
    with pytest.raises(h.HostingError) as error:b.backup_space(dict(uncompressed_bytes=10_000_000_000))
    assert error.value.code=='insufficient_space'
    with pytest.raises(h.HostingError):b.backup_space({})


@pytest.mark.parametrize('count,bitrate',[ (4,128),(3,192) ])
def test_restored_data_cannot_exceed_destination_capacity(state,monkeypatch,count,bitrate):
    monkeypatch.setattr(h,'read',lambda:dict(hosted=True,limits=dict(h.PLANS['starter'])))
    monkeypatch.setattr(b,'local_database',lambda:('postgresql://fixture@localhost/freo','freo','fixture'))
    class Connection:
        closed=False
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,*args):pass
        def fetchone(self):return (count,)
        def fetchall(self):return [(1,bitrate,None)]
        def close(self):self.closed=True
    connection=Connection()
    monkeypatch.setattr(b.recovery,'connect',lambda url:connection)
    with pytest.raises(h.HostingError) as error:b.validate_restored_capacity(dict(database='isolated'))
    assert error.value.code=='incompatible_backup' and connection.closed


def test_recording_reconciliation_preserves_custom_audio_and_enforces_sink():
    import runpy
    reconcile=runpy.run_path('scripts/admin-maintenance.py')['recording_configuration']
    template=Path('deploy/liquidsoap/station.liq.template').read_text()
    rendered=template.replace('output.file(id="freo_show_file"','output.external(id="freo_show_file"').replace('  perm=0o640, dir_perm=0o750,\n','')
    rendered=rendered.replace('{__RECORDING_DIR__ ^ "/" ^ record_key() ^ ".mp3"}','{"bounded-recorder " ^ record_key()}')
    existing=template+'\n# administrator custom audio configuration\n'
    updated=reconcile(existing,rendered)
    assert 'output.external(id="freo_show_file"' in updated
    assert updated.endswith('# administrator custom audio configuration\n')
    assert 'bounded-recorder' in updated
    with pytest.raises(ValueError):
        reconcile(existing.replace('%mp3(bitrate=192), {__RECORDING_DIR__','%mp3(bitrate=256), {__RECORDING_DIR__'),rendered)


def test_changed_database_mapping_is_rejected_before_attachment(state,monkeypatch):
    directory=state/'restored';directory.mkdir()
    (directory/'root-0').write_text('DATABASE_URL=postgresql://old-destination/db\n')
    monkeypatch.setattr(a,'settings',lambda:(state/'env',dict(DATABASE_URL='postgresql://current-destination/db')))
    with pytest.raises(h.HostingError) as error:
        b.validate_backup_database(dict(env_file='/etc/freo/freo.env'),dict(roots=['/etc/freo/freo.env']),directory)
    assert error.value.code=='incompatible_backup'
    assert 'old-destination' not in str(error.value)


def test_hosting_change_is_blocked_before_app_start_during_restore(state,monkeypatch,capsys):
    from freo_ops import hosting_admin
    original=Path
    journal=state/'operation.json'
    a.write(journal,dict(phase='attaching',operation='backup.restore'))
    monkeypatch.setattr(hosting_admin,'Path',lambda value:journal if str(value)=='/var/lib/freo-admin/operation.json' else original(value))
    assert hosting_admin.main(['hosting','activate'])==6
    assert json.loads(capsys.readouterr().out)['error']=='recovery_required'


def test_restored_service_selection_uses_restored_station_desired_state(state,monkeypatch):
    monkeypatch.setattr(a,'required_core',lambda:['freo.service'])
    monkeypatch.setattr(a,'station_rows',lambda:[dict(slug='stopped',enabled=True,desired_state='stopped'),dict(slug='running',enabled=True,desired_state='running')])
    selected=b.restored_service_selection(dict(active_units=['freo.service','freo-playout@stopped.service']))
    assert 'freo-playout@stopped.service' not in selected
    assert 'freo-playout@running.service' in selected


def test_legacy_recovery_requires_only_workers_shipped_in_that_release(state,monkeypatch):
    root=state/'source';(root/'deploy/systemd').mkdir(parents=True)
    for unit in ('freo.service','freo-ingest.service','freo-automation.service','freo-stats.service'):
        (root/'deploy/systemd'/unit).touch()
    monkeypatch.setattr(a,'source',lambda:root)
    assert 'freo-production.service' not in a.required_core()
    assert 'freo-ingest.service' in a.required_core()


def test_hosted_restore_rejects_unaware_code_before_attachment(state,monkeypatch):
    directory=state/'payload';directory.mkdir()
    app=directory/'root-0';app.mkdir();(app/'version.py').write_text("VERSION='0.3.2'\n")
    migrations=directory/'root-1';(migrations/'versions').mkdir(parents=True)
    (migrations/'versions/initial.py').write_text("revision='original'\ndown_revision=None\n")
    monkeypatch.setattr(h,'read',lambda:dict(hosted=True))
    with pytest.raises(h.HostingError) as error:
        b.validate_restored_code(dict(source='/opt/freo',version='0.3.2'),dict(roots=['/opt/freo/app','/opt/freo/migrations'],schema_revision='original'),directory)
    assert error.value.code=='incompatible_backup'


def test_legacy_inventory_allows_absent_v1_storage(state,monkeypatch):
    from freo_ops import __main__ as ops
    actual=Path
    for name in ('var/lib/freo/media','var/lib/freo/uploads','etc/freo','etc/systemd/system'):
        (state/name).mkdir(parents=True,exist_ok=True)
    (state/'etc/freo/freo.env').touch()
    monkeypatch.setattr(ops,'Path',lambda value:state/str(value).lstrip('/') if str(value).startswith('/') else actual(value))
    roots=ops.inventory('/etc/freo/freo.env',{})
    assert state/'var/lib/freo' in roots
    assert not (state/'var/lib/freo/uploads/production').exists()


def test_recovery_before_updater_created_journal(state,monkeypatch):
    monkeypatch.setattr(a,'verified_health',lambda:dict(health='healthy'))
    operation=dict(operation_id='a'*32,operation='upgrade.apply',phase='upgrading')
    result=b.resume(operation)
    assert result['upgrade_outcome']=='aborted_before_changes'
    assert operation['phase']=='complete'
    (a.UPDATES/'maintenance').parent.mkdir(parents=True,exist_ok=True)
    (a.UPDATES/'maintenance').touch()
    with pytest.raises(h.HostingError) as error:b.resume(operation)
    assert error.value.code=='recovery_required'


def test_service_restart_allows_systemd_stop_and_start_deadlines(state,monkeypatch):
    calls=[]
    monkeypatch.setattr(a,'run',lambda args,**kwargs:calls.append((args,kwargs)))
    monkeypatch.setattr(a,'verified_health',lambda:dict(health='healthy'))
    a.service_action(SimpleNamespace(action='restart',service='icecast'))
    assert calls[0][1]['timeout'] > 2*90


@pytest.mark.parametrize('policy',[b'{"hosted":false}',b'{"hosted":true,"status":"suspended"}'])
def test_configuration_attachment_never_replaces_authority_even_when_interrupted(state,monkeypatch,policy):
    source=state/'payload';source.mkdir()
    destination=state/'etc/freo';destination.mkdir(parents=True)
    (source/'hosting.json').write_bytes(b'{"hosted":true,"status":"active"}')
    (source/'publisher.gpg').symlink_to('/unapproved/trust')
    (source/'admin-upgrades.json').write_text('{"allow_candidate":true}')
    (source/'freo.env').write_text('restored customer settings')
    (source/'radio').mkdir();(source/'radio/config').write_text('restored radio')
    (destination/'hosting.json').write_bytes(policy)
    (destination/'publisher.gpg').write_bytes(b'current publisher')
    (destination/'freo.env').write_text('previous customer settings')
    (destination/'newer.conf').write_text('retained newer settings')
    authority={name:((destination/name).read_bytes(),(destination/name).stat().st_ino)
               for name in ('hosting.json','publisher.gpg')}
    directory_inode=destination.stat().st_ino
    operation=dict(operation_id='f'*32)
    actual=b.os.rename
    class Interrupted(BaseException):pass
    def interrupt_after_retaining(original,retained):
        actual(original,retained)
        if original==destination/'freo.env':raise Interrupted()
    monkeypatch.setattr(b.os,'rename',interrupt_after_retaining)
    with pytest.raises(Interrupted):b.restore_customer_configuration(operation,source,destination)
    for name,(data,inode) in authority.items():
        assert (destination/name).read_bytes()==data and (destination/name).stat().st_ino==inode
    assert not (destination/'admin-upgrades.json').exists()
    monkeypatch.setattr(b.os,'rename',actual)
    b.restore_customer_configuration(operation,source,destination)
    b.restore_customer_configuration(operation,source,destination)
    assert destination.stat().st_ino==directory_inode
    assert (destination/'freo.env').read_text()=='restored customer settings'
    assert (destination/'radio/config').read_text()=='restored radio'
    for name,(data,inode) in authority.items():
        assert (destination/name).read_bytes()==data and (destination/name).stat().st_ino==inode
    assert not (destination/'admin-upgrades.json').exists()
    retained=destination.parent/('.freo-retained-'+operation['operation_id']+'-freo-newer.conf')
    assert retained.read_text()=='retained newer settings'
