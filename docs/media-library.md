# Radio music library

Freo models music as `Artist → Album → Song`. The long-lived `tracks` row remains the Song playback identity so automation, queue requests, timed events, blocks, and confirmed history retain stable foreign keys. First-class Artist and Album records are created or reused from normalized embedded metadata. Legacy artist and album strings remain compatibility snapshots.

Station programming stays on the Song layer. Categories, tags, enable state, cue/segue values, scheduling restrictions, and confirmed play history do not alter Artist or Album identity. Catalog records remain station scoped. ImagingAsset remains the separate domain for IDs, carts, sweepers, promos, and commercials.

Authenticated admins browse `/admin/stations/<slug>/media` through Artists, Albums, and Songs views. Artist and album pages expose the natural hierarchy. The Songs workspace provides search, filtering, multi-select, and visual Category destinations. Every bulk assignment re-checks every Song and Category against the route station.

The import page accepts one MP3, multiple selections, complete albums, or a browser folder. Each file becomes an independent existing ingest job, so an invalid or duplicate file does not discard the rest of a batch. Requests allow 128 MiB per file and 512 MiB total by default; `MAX_MEDIA_UPLOAD_BYTES` and `MAX_MEDIA_BATCH_BYTES` configure those bounded limits.

The dedicated non-root `freo-ingest` worker still owns SHA-256, ffprobe validation, duplicate detection, and atomic approved storage. It additionally extracts title, artist, album artist, album, track/disc number, year, genre, ISRC, and embedded artwork. Accepted Songs become visible disabled for review while bounded offline analysis derives BPM, integrated LUFS, true peak, and leading/trailing silence cues. Analysis failure does not turn valid audio into invalid audio.

Artwork is stored under the station media root with an opaque key, associated once with the Album when suitable, and served only through an authenticated path-safe JPEG route. Public listeners receive Icecast streams. Authenticated private previews use the station-scoped audition endpoint with range support.

The root recovery CLI and trusted `app.services.media.ingest()` path remain available. The browser writes only private upload staging. It cannot provide a server path, run ffprobe directly, write approved storage, access Liquidsoap sockets, or bypass CSRF, station ownership, and mutation audit logging.


### Browser imports

Choose files or a folder, or drop either onto Import music. The screen lists selections and uploads each MP3 independently with per-file progress and results. Folder paths are reduced to file basenames for storage validation. Processing status is polled from a station-scoped authenticated endpoint; accepted files link to review and remain disabled until enabled. Failed uploads can be retried. Nginx permits the application's maximum configurable batch size; Flask enforces the configured body and per-file limits. Imaging retains its native form submission and result page.

See [Sound Room](sound-room.md) for listening, category editing, tags, automatic analysis, −16 LUFS playback normalization, and permanent deletion.
