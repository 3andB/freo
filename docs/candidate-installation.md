# Freo 1.0.1-rc.1 recovery candidate

This is a signed test candidate, not the stable release. Use disposable Ubuntu
24.04 x86_64 only. Verify the installation kit and enclosed package signatures
using the independently trusted publisher fingerprint
`B835B40E7E1A5838390256751AB72B63BEB716C3`, then verify SHA256SUMS.
Extract the verified package into a separate directory and run its bundled
`scripts/install.sh` as root for an application-fresh direct installation.
Candidate upgrades require explicit candidate approval and the normal signed
upgrade procedure in recovery-and-upgrades.md. Never reinstall over customer state.

For recovery of a v1.0.0 backup, retain the verified candidate separately with its
own offline-installed venv. Invoke its management entry point explicitly:

```
/CANDIDATE/venv/bin/python -I /CANDIDATE/scripts/hosting-admin.py backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID
/CANDIDATE/venv/bin/python -I /CANDIDATE/scripts/hosting-admin.py services recover
```

Use the returned IDs and destination installation confirmation. The restored
application may be v1.0.0; continue using the verified candidate tools throughout
resumption. Never copy individual source files over the installed release.
