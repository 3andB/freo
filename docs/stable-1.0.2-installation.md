# Freo 1.0.2 installation and upgrade

Ubuntu 24.04 x86_64. Verify detached signatures using the independently trusted
publisher fingerprint B835B40E7E1A5838390256751AB72B63BEB716C3. Verify the kit
checksum and internal SHA256SUMS before extracting the signed package.
For a fresh installation only, run scripts/install.sh as root from the extracted
package. Never run the installer over an existing installation.

For an existing 1.0.1 installation, schedule broadcast maintenance and use the
installed updater, retaining backups and verification databases:

```
sudo /opt/freo/current/venv/bin/python -m freo_ops upgrade /ABS/freo-v1.0.2.tar.gz --signature /ABS/freo-v1.0.2.tar.gz.asc --keyring /ABS/trusted-publisher.gpg --env-file /etc/freo/freo.env --backup /ABS/NEW-upgrade-backup.gpg --passphrase-file /ABS/protected-backup-key --verification-env-file /ABS/protected-verifier.env --verification-directory /ABS/NEW-verification --radio-maintenance --check
```

Use actual absolute paths. The backup and verification destinations must be new
and outside captured roots. The protected verifier environment must reference a
separate authorized PostgreSQL role with database creation permission; never grant
CREATEDB to the application role. After reviewing successful preflight, run the
same command without --check. Candidate approval is unnecessary for stable.
The ordinary admin updater intentionally refuses the changed station template.
Validate the installed system, real decoded direct/HTTPS audio, account access,
media/programming/state, and completed journals afterward. Retain verification
and recovery points; revoke temporary verifier privileges after acceptance.

For a backup containing affected older recovery code, install the verified stable
tools in a separate directory with scripts/install-python.sh and keep using that
explicit management entry point throughout restore/resume:

```
/STABLE/venv/bin/python -I /STABLE/scripts/hosting-admin.py backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID
/STABLE/venv/bin/python -I /STABLE/scripts/hosting-admin.py services recover
```

Use actual returned IDs. Preserve failed recovery state and obtain operator review
for ambiguous checkpoints; do not edit journals or globally change permissions.
See release-1.0.2.md and recovery-and-upgrades.md for scope and recovery guidance.
