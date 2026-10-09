#!/usr/bin/env python3
"""Install local administration entrypoint; never enable hosting implicitly."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from freo_ops import hosting
if os.geteuid()!=0:raise SystemExit('Root required')
directory=Path('/etc/freo')
if not directory.exists():
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
if not hosting.CONFIG.exists() and not (hosting.STATE/'enabled').exists():
    hosting.atomic(hosting.CONFIG,{'hosted':False})
import shutil
source=Path(__file__).resolve().parents[1]
guard=Path('/usr/local/lib/freo-hosting')
guard.mkdir(mode=0o755,parents=True,exist_ok=True)
guard.chmod(0o755)
(guard/'freo_ops').mkdir(mode=0o755,exist_ok=True)
(guard/'freo_ops').chmod(0o755)
(guard/'freo_ops/__init__.py').write_text('')
(guard/'freo_ops/__init__.py').chmod(0o644)
shutil.copy2(source/'freo_ops/hosting.py',guard/'freo_ops/hosting.py')
shutil.copy2(source/'scripts/hosting-guard.py',guard/'guard.py')
shutil.copy2(source/'scripts/hosting-admin-launcher.py',guard/'admin.py')
(guard/'admin.py').chmod(0o755)
launcher=Path('/usr/local/sbin/freo-admin')
launcher.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /usr/local/lib/freo-hosting/admin.py "$@"\n')
launcher.chmod(0o755)

# The updater retains the existing Icecast base unit. Guard it explicitly too.
from freo_ops.hosting_recovery import install_service_guards
install_service_guards()

# Lifecycle identity is local and never enrolls or enables hosted mode.
from freo_ops.admin_identity import initialize, STATE
initialize()
# Retain a trusted executable runtime for recovery from older application code.
runtime=STATE/'runtime'
if runtime.exists() or runtime.is_symlink():runtime.unlink()
runtime.symlink_to(source)
