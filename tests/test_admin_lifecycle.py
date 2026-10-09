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


def test_service_recovery_cannot_restore_database_implicitly(state):
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
    monkeypatch.setattr(b,'disk_check',lambda paths:None)
    monkeypatch.setattr(b,'roots',lambda:[])
    with pytest.raises(h.HostingError) as error:
        b.restore_start(SimpleNamespace(confirm_installation='0919533f-7811-45f2-ba08-5648daa930c9',id='c'*32))
    assert error.value.code=='recovery_required'
