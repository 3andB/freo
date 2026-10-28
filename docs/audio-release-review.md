# Audio release verification — 17 September 2026

Commit `183e281` adds WAV, M4A, MP3 and FLAC music imports, compatible private
previews, the daily account-wide import reminder, and station-specific bitrate,
AGC, multiband compression and EQ settings. See
[audio imports and station sound](audio-import-and-processing.md) for supported
codecs, processing behavior and recovery instructions.

## Production deployment

The production database was backed up in PostgreSQL custom format before
migration. The release backup also contains the previous source revision,
runtime configuration and station-state manifest. It is stored outside the
repository under `/var/backups/freo/audio-release-20260917T052407Z`, with access
restricted to root. Restoring that database into an isolated PostgreSQL instance
and applying the new migration preserved the station records.

Migration `c84a2e019b36` was applied successfully. Alembic's schema comparison
reported no further changes. Existing station IDs, desired states and 64 kbps
bitrates were preserved; additional processing remains disabled.

The updated provisioner service was installed and systemd reloaded. Web,
automation, ingest, microphone, central API and statistics services restarted.
Both managed station configurations passed Liquidsoap validation. The running
station restarted; the other station remained stopped. Diagnostic playout
restarted and the provisioning timer remains enabled.

Icecast stopped responding after its configuration reload during deployment.
A full service restart recovered it. Subsequent checks confirmed healthy
Icecast, station playout and audio delivery. Audio-setting changes use the
station-only apply path and do not reload Icecast.

Installation validation passed, including migration state, service identities,
media permissions, private listeners, automation health and diagnostic MP3
output. Public HTTPS health, readiness, station API and player routes passed.
Authenticated HTTPS checks confirmed all four import formats and the bitrate
and processing settings. Samples from the live and diagnostic mounts decoded
as 64 kbps MP3. Production statistics resumed fresh online observations.

## Automated verification

The release checks include isolated FFmpeg import/preview decoding, native
Liquidsoap format playback and bitrate checks, browser workflows, private media
access, failed-setting recovery, and populated migration roundtrips. Separate
PostgreSQL suites passed all eight tests. The pinned external API validator
check passed with its dependencies installed only in a temporary test directory.

JavaScript and shell syntax, Python dependency consistency, systemd service
validation and Git whitespace checks passed. Test fixtures use isolated media
and databases; generated test audio and database backups are not committed.

The full run used `FREO_ENGINE_TEST=1` and `FREO_SCHEDULE_SCALE=1` with the
installation environment disabled. It completed 494 collected checks in
29 minutes 51 seconds: 483 passed, 10 skipped, and one failed. The failure was
an eight-second browser timeout waiting for the station-settings save message;
the settings POST and redirected page both succeeded. The same workflow passed
in two isolated retries, including a final 17.69-second run after the full suite.
The ten skips comprise the eight PostgreSQL checks and
one external contract check passed separately, plus the optional demonstration
screenshot generator. The full run therefore was not a clean first pass.

All native audio-engine checks passed, including supported-format playback,
64/96/128 kbps MP3 headers, enabled processing, microphone handoff, scheduled
fades and multi-station creation/deletion isolation. The 100,000-song scheduling
benchmark passed. Browser checks covered import notice behavior, supported
extensions, audio settings, mobile layouts, public playback and persistent
workspace audio. The run also reported 18 dependency/fixture warnings.
