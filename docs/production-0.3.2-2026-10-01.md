# Production 0.3.2 deployment — 1 October 2026

The owner authorized updating production, committing and pushing the deployment
record, and restarting services. freo.world now runs the published, signed
0.3.2 application from source `83200e6508654bea13f404e9d5699a8ad3eae19d`.
The prior application was 0.3.0 at `4ff69067e3a3f1b4a488b7ea8f8598ac25a27bda`.

## Release and recovery

- Verified the publisher signature and application archive SHA-256:
  `7bfc8a573a59dfa210478da9c2b80fccbb0ebcde297a85d4ae56856d96709c4f`.
- Verified all 448 signed payload files. The installed payload still matches
  that manifest after activation; no application archive was rebuilt or changed.
- Preserved the previous Git history and source in the private deployment backup.
  Synchronized the stale local 0.3.2 tag with the published tag after this backup.
- Passed the signed updater's preflight. Schema remains `c83d4e5f9012`;
  no radio/proxy template change was needed.
- Installed the exact bundled Python dependencies offline into a separate
  release virtual environment, including both PostgreSQL drivers and the live
  microphone dependencies.
- Stopped the previously active Freo units under the updater's maintenance
  guards. Created an encrypted database/filesystem backup, restored it into a
  separate PostgreSQL cluster and filesystem tree, and verified database values,
  sequences and file contents. The updater's pre-existing-record preservation
  checks passed before activation.

Private recovery material is retained under
`/var/backups/freo/production-032-20261001T000518Z`. The backup passphrase is
stored separately in a root-only file under `/root/.config/freo-recovery`.
The isolated verification cluster was stopped after validation; its restored
database and files remain available. No production database was replaced.

## Runtime layout and activation

The supported updater adopted the versioned runtime layout:

- `/opt/freo/current` points to
  `/opt/freo/releases/9d16aee743ab4ad3adaf5eddec4725ae`.
- Managed services use that release and `/etc/freo/freo.env`.
- `/opt/freo` remains the source checkout, fast-forwarded to published main
  `3412ca8846c06a7a2bec276e7b43e83f603ef54a` before this documentation commit.
- The previous virtual environment and original environment file are retained.
  Runtime commands should use `/opt/freo/current/venv` with
  `FREO_ENV_FILE=/etc/freo/freo.env` from `/opt/freo/current`.
- Runtime `current` and `releases` paths are excluded from Git tracking.

The updater completed with exit 0 and journal phase `complete`. Web, automation,
ingest, statistics, central reporting, live microphone, diagnostic playout and
both previously running managed station engines restarted. Existing station
programming and running/stopped intent were preserved. No server reboot was
performed for this deployment. The web service started at 00:07:25 UTC.

## Production verification

- Installed dependency, Nginx configuration, schema, service, permissions,
  private-listener, health/readiness and diagnostic MP3 checks passed.
- The shipped installation validator passed using the versioned runtime and
  stable environment path. Its legacy `$install_dir/.env` references were
  redirected to `/etc/freo/freo.env` in the invocation only; signed source files
  and validation assertions were unchanged.
- Local Nginx/admin login and external HTTPS access checks passed, with existing
  accounts retained. Public homepage, login, both players, station listing and
  health endpoints returned HTTP 200.
- The publicly served workspace JavaScript exactly matched the signed release.
- Both public station streams supplied 131,072 MP3 bytes and decoded with FFmpeg:
  10.92 seconds for freo-demo (RMS 0.189698), and 16.38 seconds for freo-demo-2
  (RMS 0.127078).
- Fresh worker observations confirmed both stations online in AUTO, current
  playback decisions present, backup tone off and no observation errors.
- All eight checked application/managed-engine services were active with zero
  automatic restarts. Their error-priority journals had no entries after
  activation. The historical failed `freo-live-stress-20260921.service` was
  already present before this deployment and was not restarted or erased.
- The successful 00:08:01 UTC heartbeat reports installed and latest version
  0.3.2 with status **Current**.

Evidence, including updater output, installed validation and public-page/audio
results, is retained with the private backup. These are deployment checks;
the published release's broader regression and fresh-VM acceptance records
remain unchanged. This run did not test certificate renewal or an on-air browser
microphone session.
