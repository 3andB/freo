# Audio imports and station sound

Music imports accept MP3, FLAC, M4A containing AAC or ALAC, and WAV containing
8-bit unsigned PCM, 16/24/32-bit signed PCM or 32/64-bit floating-point PCM.
The worker checks the actual container and codec, one mono/stereo audio stream,
duration and file size. Video is rejected; embedded cover artwork is allowed.
The existing per-song upload limit still applies, so large WAV files may need
lossless FLAC conversion before upload. Protected or undecodable files fail validation.

Original audio and its checksum are retained for broadcasting. Non-MP3 imports
also undergo full decoding to a private 192 kbps MP3 browser preview. The ingest
worker writes previews under `<station>/previews`; the web service only reads
them through the authenticated song audition route, which supports seeking.
Failed imports remove partial previews. Permanent song deletion removes its
preview too, and storage statistics include preview bytes in music storage.
Browser preview before uploading depends on the browser's decoder; metadata
from the original file is extracted by the worker after upload. A failed local
preview does not prevent importing a supported file.

The importer shows a copyright reminder once per user account per UTC calendar
date, shared across stations, devices and sessions. A CSRF-protected atomic
database update claims the daily reminder when the import page opens. Cancel
returns to Music without uploading; it still counts as having shown the notice.
The reminder is informational and does not determine or grant copyright rights.

## Stream quality and processing

Station settings offers 64, 96 and 128 kbps MP3 broadcasting, independently of
upload and preview quality. Existing stations keep 64 kbps and all additional
processing starts disabled. The three rates use approximately 28.8, 43.2 and
57.6 MB per listener-hour respectively, before transport overhead.

Optional processing applies to the mixed broadcast, before the schedule switch
fade and the existing final output limiter:

1. AGC targets −16 LUFS, with gain bounded to ±6 dB, a 3-second measurement
   window, slow gain increases, and a −40 dB silence threshold. It adds no
   lookahead delay. Because it acts on the mixed program, it can gently raise
   sustained quiet passages; disable it when preserving all manual level
   changes is preferred.
2. EQ uses broad peak filters at 100 Hz, 1 kHz and 8 kHz, each limited to ±6 dB.
3. The gentle multiband preset uses 200 Hz and 2.5 kHz crossovers, 1.5:1
   compression, −18 dB thresholds, 20 ms attack, 250 ms release and no makeup
   gain. Liquidsoap's multiband operator includes its own safety limiting.

Song loudness normalization remains in place. Private song previews do not
include station processing; listen through the station monitor to assess the
broadcast sound. Synthetic signal tests verify decoding, output and finite
levels, but cannot substitute for listening to representative programming.

Saving audio settings queues a revision-checked change. The existing root-run
provisioning worker applies at most one audio change per invocation. It checks
the generated Liquidsoap configuration, keeps a revision-specific backup, and
restarts only the selected station if it was running or desired running. A
stopped station stays stopped. The worker waits for audio before updating the
active settings shown in the app. Configuration/restart failures restore the
previous configuration and report a retryable error. A failed recovery is
reported separately and leaves the backup available. Worker interruption during
application reuses the original backup on retry. Other Icecast mounts and Nginx
are not reconfigured by an audio change.

## Rollout

1. Back up the database and deploy migration `c84a2e019b36` with
   `venv/bin/flask --app wsgi db upgrade` before starting updated web/workers.
2. Install the updated `deploy/systemd/freo-provision.service` and run
   `systemctl daemon-reload`; its timeout accommodates validation and recovery.
3. Restart the web and ingest services and ensure `freo-provision.timer` is
   enabled. Existing audio engines can continue until a station audio change
   or their next normal restart renders the updated template.
4. Existing default media ACLs propagate to new preview directories. Run
   `scripts/media-web-access.sh` as root if repairing an older installation's
   web preview permissions.
5. Import a disposable file of each format, check metadata, private preview and
   actual broadcast playback. Check station quality changes and restoration
   on a disposable station before changing a live station's sound.

Downgrade refuses pending/failed audio changes, non-64-kbps streams, enabled
processing, and retained WAV/M4A/FLAC songs. Restore compatible settings and
export/remove the new-format songs first, or restore the pre-deployment backup.

Validation covers actual FFmpeg ingestion and preview decoding, Liquidsoap
playback of every supported family, real MPEG bitrate headers at all three
rates, enabled processing and full-template syntax, runtime failure recovery,
private preview isolation and deletion, browser upload/settings/reminder flows,
and populated SQLite/PostgreSQL migration roundtrips.
