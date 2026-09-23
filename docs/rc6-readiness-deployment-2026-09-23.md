# RC6 readiness fixes deployed — 2026-09-23

The owner authorized deploying the completed audit fixes before the separate
version-awareness implementation. Production and main moved by fast-forward from
`92484ce413a05ce3db8f80082a3c502849bc0e67` to
`ab8466a68765312a4fdb1f5b08e2fa3f331dd7c3`, preserving all 13 audit commits.
Main and origin/main were verified synchronized after deployment.

The deployed code was already validated by the full candidate run with 1,059
passed and 12 skipped checks, plus successful recovery validation. Main push
triggered the existing recovery workflow (run `35922478793`). No release/signing
workflow was triggered, and no tag, GitHub Release or stable/latest pointer moved.

## Recovery and activation

An exclusive upgrade lock and existing maintenance guards protected deployment.
A fresh encrypted database/filesystem backup was restored to a separate temporary
PostgreSQL cluster; database values and sequences were verified preserved before
activation. Source history and the previous source archive were also retained.
No database schema, dependency or service-definition changes were required.
Tracked source readability was verified for the service account before startup,
avoiding the previous private-umask deployment issue.

Previously active Freo services were stopped, the clean production checkout was
fast-forwarded, and the same services/timers were restarted. Both station mounts
were allowed time to reconnect before audio was checked. The temporary recovery
cluster was stopped after verification.

Private evidence is in:
`/var/backups/freo/rc6-readiness-deploy-20260923T212657Z`.

## Post-deployment checks

- Installed validation passed: web, database/migration head, scheduling imports,
  radio services, private listeners, health, and existing admin login.
- Authenticated GET-only browser checks passed for installation, feedback,
  station settings, tags, categories, music library and website at 390/820/1440
  pixels, with no overflow or severe browser errors.
- The player retained its circular center, colored outer ring and stationary
  artwork. Statistics rendered the map and refreshed the historical chart.
- Public HTTPS health/readiness and both actual player URLs returned HTTP 200.
  The second station's published URL is `/player/freo-demo-2`.
- Both public streams supplied 65,536-byte MP3 samples that FFmpeg decoded.
- All eight monitored services were active with no automatic restarts recorded.
- All 15 preserved RC5 artifact hashes matched; source `739a0ed` and acceptance
  `2144f36` remain ancestors of main with their original IDs. The preserved RC5
  VM was not accessed, and RC5 artifacts were not rebuilt or re-signed.

This deployment runs `0.3.0-rc.6.dev1`. The separate version-awareness branch uses
`0.3.0-rc.6.dev2` and is deliberately not deployed by this operation. RC6 remains
in development; fresh/populated disposable-VM installation and upgrade acceptance
remain outstanding before an eventual frozen candidate.
