"""Provisioning must produce service-readable paths under systemd's umask."""
import os
import stat
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import station_runtime as runtime
from app.services.stations import create_station
from tests.test_stations import station_app


@pytest.mark.parametrize('existing_private_dirs', [False, True])
def test_render_permissions_under_provisioner_umask(station_app, tmp_path, monkeypatch,
                                                  existing_private_dirs):
    root = tmp_path / 'freo'
    radio = root / 'radio'
    radio.mkdir(parents=True)
    (radio / 'icecast.xml').write_text('<icecast/>')
    configs = radio / 'stations'
    snippets = tmp_path / 'snippets'
    secrets = root / 'secrets' / 'stations'
    for name, path in [('ROOT', root), ('CONFIGS', configs),
                       ('SNIPPETS', snippets), ('SECRETS', secrets)]:
        monkeypatch.setattr(runtime, name, path)
    monkeypatch.setattr(runtime, 'require_root', lambda: None)
    monkeypatch.setattr(runtime.os, 'chown', lambda *args: None)
    monkeypatch.setattr('pwd.getpwnam', lambda name: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr('grp.getgrnam', lambda name: SimpleNamespace(gr_gid=os.getgid()))
    monkeypatch.setattr(runtime, 'run_checked', Mock())
    monkeypatch.setattr('app.services.media.refresh_playlist', Mock())
    if existing_private_dirs:
        configs.mkdir(mode=0o700)
        snippets.mkdir(mode=0o700)

    with station_app.app_context():
        station = create_station('First station', '1', pending=True)
        previous_umask = os.umask(0o077)
        try:
            runtime.render(station)
        finally:
            os.umask(previous_umask)

    # Directory traversal is required even when the config itself is readable.
    assert stat.S_IMODE(configs.stat().st_mode) == 0o755
    assert stat.S_IMODE(snippets.stat().st_mode) == 0o755
    assert stat.S_IMODE((configs / '1.liq').stat().st_mode) == 0o640
    assert stat.S_IMODE((snippets / '1.conf').stat().st_mode) == 0o644
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o700
    assert stat.S_IMODE((secrets / '1.json').stat().st_mode) == 0o600
    validation = runtime.run_checked.call_args_list[0].args[0]
    assert validation[:6] == ['/usr/sbin/runuser', '-u', 'freo-playout', '--',
                              '/usr/bin/liquidsoap', '--check']
