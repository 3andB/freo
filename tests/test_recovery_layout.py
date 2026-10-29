"""Real filesystem and process-boundary recovery regressions (run as root)."""
import grp
import os
from pathlib import Path
import subprocess
import pytest
from freo_ops import recovery_layout as layout
from freo_ops.hosting import HostingError


@pytest.mark.parametrize('mask', [0o022, 0o077])
@pytest.mark.parametrize('existing', [False, True])
def test_managed_parent_traversable(tmp_path, mask, existing):
    parent = tmp_path/'releases'
    if existing: parent.mkdir(mode=0o700)
    previous = os.umask(mask)
    try:
        layout.managed_directory(parent)
        release = parent/'recovered-test'
        layout.managed_directory(release)
        layout.managed_directory(parent)
    finally: os.umask(previous)
    assert parent.stat().st_mode & 0o777 == 0o755
    assert parent.stat().st_uid == parent.stat().st_gid == 0
    # pytest's private ancestors are deliberately opened for this traversal test.
    for ancestor in (tmp_path, tmp_path.parent): ancestor.chmod(0o755)
    result = subprocess.run(['runuser','-u','nobody','--','test','-x',str(release)])
    assert result.returncode == 0


@pytest.mark.parametrize('unsafe', ['symlink','file','writable','owner'])
def test_unsafe_parent_is_rejected_without_changing_target(tmp_path, unsafe):
    target = tmp_path/'target'; target.mkdir()
    path = tmp_path/'releases'
    if unsafe == 'symlink': path.symlink_to(target)
    elif unsafe == 'file': path.touch()
    else:
        path.mkdir()
        if unsafe == 'writable': path.chmod(0o777)
        else: os.chown(path, 65534, 65534)
    before = target.stat()
    with pytest.raises(HostingError): layout.managed_directory(path)
    assert target.stat() == before


@pytest.mark.parametrize('source', ['/opt/freo', '/opt/freo/releases/old'])
@pytest.mark.parametrize('header', ['#!{source}/venv/bin/python -s\n', '#!{source}/venv/bin/python3.12\n', '#!/bin/sh\n\'\'\'exec\' "{source}/venv/bin/python" "$0" "$@"\n\' \'\'\'\n'])
def test_launcher_repeated_from_verified_input(tmp_path, source, header):
    release = source+'/releases/recovered-test'
    original = tmp_path/'verified'; original.mkdir()
    target = tmp_path/'attached'; target.mkdir()
    body = ('print("'+source+'/unrelated")\n').encode()
    data = header.format(source=source).encode()+body
    script = original/'gunicorn'; script.write_bytes(data); script.chmod(0o751)
    expected = layout.launcher_bytes(data,source,release)
    assert release.encode()+b'/venv/bin/python' in expected
    assert expected.endswith(body)
    assert layout.launcher_bytes(expected,source,release) == expected
    for _ in range(4):
        layout.relocate_launchers(original,target,source,release)
        assert (target/'gunicorn').read_bytes() == expected
        assert (target/'gunicorn').stat().st_mode & 0o777 == 0o751


@pytest.mark.parametrize('point', ['before_replace','after_replace','after_all'])
def test_interruption_resumes_without_checkpoint(tmp_path, monkeypatch, point):
    source = tmp_path/'verified'; source.mkdir()
    target = tmp_path/'attached'; target.mkdir()
    data = b'#!/opt/freo/venv/bin/python -s\nprint("/opt/freo/body")\n'
    for name in ['flask','gunicorn','pip']:
        (source/name).write_bytes(data); (source/name).chmod(0o755)
    replace = layout.os.replace
    class Interrupted(BaseException): pass
    def interrupted(*args):
        if point == 'before_replace': raise Interrupted()
        replace(*args)
        raise Interrupted()
    if point != 'after_all':
        monkeypatch.setattr(layout.os,'replace',interrupted)
        with pytest.raises(Interrupted): layout.relocate_launchers(source,target,'/opt/freo','/opt/freo/releases/recovered-id')
        monkeypatch.setattr(layout.os,'replace',replace)
    else: layout.relocate_launchers(source,target,'/opt/freo','/opt/freo/releases/recovered-id')
    layout.relocate_launchers(source,target,'/opt/freo','/opt/freo/releases/recovered-id')
    for script in target.iterdir():
        assert script.read_bytes() == b'#!/opt/freo/releases/recovered-id/venv/bin/python -s\nprint("/opt/freo/body")\n'


@pytest.mark.parametrize('existing', [False,True])
@pytest.mark.parametrize('same', [False,True])
def test_canonical_environment_preserves_secrets(tmp_path, existing, same):
    expected = b'SECRET_KEY="opaque $value"\n# keep bytes\n'
    source = tmp_path/'restored.env'; source.write_bytes(expected);source.chmod(0o600)
    destination = source if same else tmp_path/'freo.env'
    if existing and not same: destination.write_bytes(b'old');destination.chmod(0o600)
    layout.canonical_environment(source,destination)
    assert destination.read_bytes() == expected
    assert source.read_bytes() == expected
    info = destination.stat()
    assert (info.st_uid,info.st_gid,info.st_mode & 0o777) == (0,grp.getgrnam('freo').gr_gid,0o640)
    layout.canonical_environment(destination,destination)
    assert destination.read_bytes() == expected


def test_environment_symlink_rejected(tmp_path):
    source = tmp_path/'source'; source.write_bytes(b'secret')
    destination = tmp_path/'freo.env'; destination.symlink_to(source)
    with pytest.raises(HostingError): layout.canonical_environment(source,destination)
    assert source.read_bytes() == b'secret'


@pytest.mark.parametrize('kind', ['file', 'tree'])
def test_verified_attachment_is_durable_before_visibility(tmp_path, monkeypatch, kind):
    import stat
    source = tmp_path/'verified'
    if kind == 'tree':
        source.mkdir(); (source/'nested').mkdir(); payload = source/'nested/secret.env'
        external = tmp_path/'external'; external.write_bytes(b'leave unchanged')
        (source/'outside').symlink_to(external)
    else: payload = source
    payload.write_bytes(b'SECRET=exact\x00bytes\n'); payload.chmod(0o600)
    staged, target = tmp_path/'staged', tmp_path/'attached'
    original_fsync, original_rename = layout.os.fsync, layout.os.rename
    synced = set(); renamed = []
    def fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode): synced.add(os.readlink('/proc/self/fd/'+str(fd)))
        return original_fsync(fd)
    def rename(old, new):
        expected = staged/'nested/secret.env' if kind == 'tree' else staged
        assert str(expected) in synced, 'Attachment became visible before its contents were durable'
        if kind == 'tree': assert str(external) not in synced
        renamed.append((old,new)); return original_rename(old,new)
    monkeypatch.setattr(layout.os,'fsync',fsync);monkeypatch.setattr(layout.os,'rename',rename)
    layout.attach_verified_copy(source, staged, target)
    result = target/'nested/secret.env' if kind == 'tree' else target
    assert result.read_bytes() == payload.read_bytes() and result.stat().st_mode & 0o777 == 0o600
    assert len(renamed)==1 and not staged.exists()
    if kind == 'tree': assert external.read_bytes()==b'leave unchanged' and (target/'outside').is_symlink()


def test_attachment_sync_failure_leaves_target_absent_and_resume_recopies(tmp_path,monkeypatch):
    source=tmp_path/'verified';source.mkdir();(source/'config').write_bytes(b'complete managed proxy\n')
    staged,target=tmp_path/'staged',tmp_path/'target';real=layout.os.fsync
    monkeypatch.setattr(layout.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('injected storage failure')))
    with pytest.raises(OSError):layout.attach_verified_copy(source,staged,target)
    assert not target.exists()
    (staged/'config').write_bytes(b'torn')
    monkeypatch.setattr(layout.os,'fsync',real);layout.attach_verified_copy(source,staged,target)
    assert (target/'config').read_bytes()==b'complete managed proxy\n'


def test_atomic_symlink_interruption_retains_previous_target(tmp_path,monkeypatch):
    destination=tmp_path/'current';destination.symlink_to('old')
    original=layout.os.replace
    def fail(*args):raise OSError('injected before replacement')
    monkeypatch.setattr(layout.os,'replace',fail)
    with pytest.raises(OSError):layout.atomic_symlink(destination,'new')
    assert os.readlink(destination)=='old'
    monkeypatch.setattr(layout.os,'replace',original);layout.atomic_symlink(destination,'new');layout.atomic_symlink(destination,'new')
    assert os.readlink(destination)=='new'
    assert not list(tmp_path.glob('.freo-link-*'))


def test_hosting_proxy_atomic_interruption_keeps_managed_contents(tmp_path,monkeypatch):
    from freo_ops import hosting_recovery as authority
    target=tmp_path/'managed.conf';expected=b'proxy_request_buffering off;\nproxy_http_version 1.1;\n';target.write_bytes(expected)
    monkeypatch.setattr(authority,'Path',lambda name:target)
    monkeypatch.setattr(authority.subprocess,'run',lambda *args,**kwargs:None)
    original=layout.os.replace
    monkeypatch.setattr(layout.os,'replace',lambda *args:(_ for _ in ()).throw(OSError('before atomic replacement')))
    with pytest.raises(OSError):authority.protect_request_spooling()
    assert target.read_bytes()==expected
    monkeypatch.setattr(layout.os,'replace',original);authority.protect_request_spooling()
    assert target.read_bytes()==expected and target.stat().st_mode & 0o777==0o644
    target.write_bytes(b'operator customization')
    with pytest.raises(HostingError):authority.protect_request_spooling()
    assert target.read_bytes()==b'operator customization'


def test_customer_entry_attachment_persists_both_rename_parents(tmp_path,monkeypatch):
    parent=tmp_path/'etc';destination=parent/'freo';destination.mkdir(parents=True)
    source=tmp_path/'verified';source.write_bytes(b'opaque secret\n');source.chmod(0o640)
    synced=[];real=layout.sync_directory
    def record(path):synced.append(Path(path));return real(path)
    monkeypatch.setattr(layout,'sync_directory',record)
    layout.attach_verified_copy(source,parent/'.staged-env',destination/'freo.env')
    assert synced[-2:]==[destination,parent]
    assert (destination/'freo.env').read_bytes()==b'opaque secret\n'


def test_hosting_guard_installation_uses_only_standard_library(tmp_path):
    # Fresh provisioning invokes system Python before app dependencies exist.
    # -I -S excludes user paths and all site packages, including psycopg2.
    import sys
    root=Path(__file__).resolve().parents[1]
    script='''
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from freo_ops import hosting_recovery as authority
root=Path(sys.argv[2]);root.mkdir()
authority.Path=lambda value:root if value=='/etc/systemd/system' else Path(value)
authority.install_service_guards()
files=list(root.glob('*.service.d/hosting-authority.conf'))
assert len(files)==5
for p in files:
 assert p.read_text().startswith('[Service]\\nExecCondition=/usr/bin/python3 ')
 assert p.stat().st_mode & 0o777 == 0o644
'''
    subprocess.run([sys.executable,'-I','-S','-c',script,str(root),str(tmp_path/'units')],check=True,capture_output=True,text=True)


def test_private_operation_directory_persists_new_ancestors(tmp_path,monkeypatch):
    from freo_ops import admin,upgrade
    target=tmp_path/'restores/operation'
    seen=[];real=upgrade.sync_directory
    def sync(path):seen.append(Path(path));return real(path)
    monkeypatch.setattr(upgrade,'sync_directory',sync)
    assert admin.private_directory(target)==target
    assert seen==[target,*target.parents]
    assert target.stat().st_mode & 0o777==0o700


def test_maintenance_removal_persisted_before_return(tmp_path,monkeypatch):
    from freo_ops import upgrade
    (tmp_path/'maintenance').write_text('guard')
    seen=[];real=upgrade.sync_directory
    def sync(path):assert not (tmp_path/'maintenance').exists();seen.append(path);return real(path)
    monkeypatch.setattr(upgrade,'sync_directory',sync)
    upgrade.set_maintenance(tmp_path,False)
    assert seen==[tmp_path]
