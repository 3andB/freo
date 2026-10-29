# Freo 1.0.2-rc.2 microphone correction candidate

This is a signed test candidate, not the stable release. Use disposable Ubuntu
24.04 x86_64 only. Verify the installation kit and enclosed package signatures
using the independently trusted publisher fingerprint
`B835B40E7E1A5838390256751AB72B63BEB716C3`, then verify SHA256SUMS.
Extract the verified package into a separate directory and run its bundled
`scripts/install.sh` as root for an application-fresh direct installation.
Candidate upgrades require explicit candidate approval and the explicit radio-maintenance
upgrade procedure. The ordinary admin updater intentionally refuses this radio-template change. Never reinstall over customer state.

For recovery of a v1.0.0 backup, retain the verified candidate separately with its
own offline-installed venv. Invoke its management entry point explicitly:

```
/CANDIDATE/venv/bin/python -I /CANDIDATE/scripts/hosting-admin.py backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID
/CANDIDATE/venv/bin/python -I /CANDIDATE/scripts/hosting-admin.py services recover
```

Use the returned IDs and destination installation confirmation. The restored
application may be v1.0.0; continue using the verified candidate tools throughout
resumption. Never copy individual source files over the installed release.

This candidate also includes the published 1.0.1 recovery corrections and staged-copy durability fixes. It keeps
a healthy live microphone quiet when muted, while retaining input-loss and
lease-expiry fallback. Existing installations require the explicit radio-maintenance updater, which
validates and renders existing managed stations with the corrected template. See
[1.0.2 candidate notes](release-1.0.2-rc.2.md) for scope and test status.
