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
