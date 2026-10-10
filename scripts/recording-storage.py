#!/usr/bin/env python3
"""Root-run recording storage provisioning. Never invoked by the web/worker.

Usage: python scripts/recording-storage.py MEDIA_ROOT STATION_SLUG
Also writes the station service's narrow ReadWritePaths override. For a custom
media root, run this before rendering/restarting the corresponding V1 station.
"""
import argparse
import grp
import os
from pathlib import Path
import pwd
import re
import subprocess


def provision(root, slug, unit_root=Path('/etc/systemd/system')):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?', slug):
        raise ValueError('Invalid station slug')
    root = Path(root)
    if not root.is_absolute() or any(c in str(root) for c in '\n\r%"\\'):
        raise ValueError('Media root must be an absolute systemd-safe path')
    station = root / slug
    directory = station / 'recordings'
    for path in (root, station, directory):
        if path.is_symlink():
            raise ValueError('Symlink storage is forbidden')
    if not root.is_dir():
        raise ValueError('Provision the existing Freo media root first')
    if not station.exists():
        station.mkdir(mode=0o750)
        os.chown(station, pwd.getpwnam('freo-ingest').pw_uid, grp.getgrnam('freo-playout').gr_gid)
        os.chmod(station, 0o2750)
    directory.mkdir(mode=0o750, exist_ok=True)
    os.chown(directory, pwd.getpwnam('freo-playout').pw_uid, grp.getgrnam('freo-playout').gr_gid)
    os.chmod(directory, 0o2750)
    subprocess.run(['setfacl', '-m', 'u:freo:r-x,u:freo-automation:r-x', str(station)], check=True)
    subprocess.run(['setfacl', '-m', 'u:freo:r-x,u:freo-automation:rwx,d:u:freo:r-x,d:u:freo-automation:r-x', str(directory)], check=True)
    override = unit_root / f'freo-playout@{slug}.service.d'
    override.mkdir(parents=True, exist_ok=True)
    if override.is_symlink() or (override/'recordings.conf').is_symlink():
        raise ValueError('Symlink service override is forbidden')
    worker = unit_root / 'freo-automation.service.d'
    worker.mkdir(parents=True, exist_ok=True)
    target = worker / f'recordings-{slug}.conf'
    if worker.is_symlink() or target.is_symlink():
        raise ValueError('Symlink service override is forbidden')
    target.write_text(f'[Service]\nReadWritePaths="{directory}"\n')
    (override/'recordings.conf').write_text(f'[Service]\nReadWritePaths="{directory}"\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('media_root', type=Path)
    parser.add_argument('slug')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Root is required')
    provision(args.media_root, args.slug)
