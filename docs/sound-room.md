# Music workspace

The Songs tab of Music contains the listening and organization workspace. The former Sound Room URL redirects to [Playlists](playlists.md). Changes use existing station Song, Category, and MusicTag records. Category membership feeds the existing rotations; it does not specify playback order.

- Play before a song title starts private preview. The bottom player offers seeking, volume, and normalized/original listening. Only one preview plays at a time, and filters do not interrupt it.
- Select song checkboxes, then drag a song onto a category/tag or use Apply. A tag's grip can also be dragged onto a song. Touch users drag the grip; the rest of the row permits scrolling. Escape cancels a drag.
- Click a category name or chip to open its editor. Edit its name, description, and enabled state. Browse songs to add, or view current members and remove them. The stable category slug and ID remain unchanged.
- Create colored tags, rename them, apply to groups, and filter by them. Undo records only membership changes actually made, is station/operator scoped, single-use, and expires after one hour.
- Select a song for notes, processing, tags, categories, and analysis. Unsaved notes/category edits are protected during polling; notes detect conflicting saves.

## Analysis and loudness

The ingest worker processes explicit analysis requests first, then ingest jobs, then the unfinished accepted-song backlog, one at a time. ffmpeg runs at lower priority with a bounded timeout. Failure retries back off, stop after three attempts, and can be retried explicitly. Restart recovery restores interrupted work. Analysis validates finite LUFS/true-peak measurements and preserves manually entered cue points and notes. Successful analysis enables imports that still have automatic enable pending; manual disables remain disabled.

Stations default to −16 LUFS. Music can set the target between −30 and −12 LUFS. `gain_for` derives a fixed gain from measured integrated LUFS and limits boosts by the measured true peak (−1.5 dBTP ceiling) and a 12 dB maximum boost. Songs unable to reach the target are labeled Peak limited or Gain limited. Unanalyzed songs use unity gain and show Needs analysis. Originals are never rewritten.

The automation worker adds a bounded `freo_gain` annotation to music requests. Liquidsoap applies this gain before crossfading and a zero-makeup output limiter reduces overlap peaks. New targets affect newly queued songs, not already submitted requests. Browser previews use the same gain policy. This is overall song loudness matching, not constant momentary loudness; lossy encoding and overlapping music can alter final measured peaks. `test_loudness_playout.py` measures actual Liquidsoap output with differently leveled test signals.

## Permanent deletion

Music's song menu and the song edit page expose explicit permanent-delete confirmation. This is a master-library operation across every channel. Acceptance immediately removes the song from Music and broadcast eligibility. It removes song-specific Events, Block items, playlist membership, categories, tags, cart assignments, saved cues, visual schedule sources/inserts, feedback, and play history. Unrelated songs and programming containers remain.

The automation worker clears loaded and future requests using `freo_music.remove <decision-id>`. The engine checks the identity itself, so a track boundary cannot remove the following song. The ingest worker waits for acknowledgement on running channels, then removes the original, preview, unshared artwork, import metadata, and track record. Other ingest jobs can continue while playback cleanup is pending. Migrated Imaging songs also lose their retained legacy source and identity, preventing a later migration from recreating them. Missing files are harmless on retry. A generic deletion audit remains; shared album artwork remains in use. A future intentional reimport receives a new song UUID.

The library polls deletion completion and offers a status/retry link on failure. The operation page also polls when opened through workspace navigation. Processing, sharing, Events, Blocks, and queues never require manual cleanup before accepting deletion.

## Channel availability and action feedback

Channel availability is at the bottom of the song editor. Matching shortcuts above Flag in the Music inspector and below Tags and categories open the same availability dialog. Direct and inherited artist/album sharing are distinguished. Saves show progress and errors; successful dialog saves close automatically.

Song action menus close on selection, outside click, or Escape. Processing shows queued, processing, complete, and failed states; duplicate requests are disabled. Permission failures, missing files, and timeouts have actionable messages, with the underlying error logged by the worker.

## September 19 deployment

The engine template and automation worker must be released together: existing engines need the `freo_music.remove` command before the new deletion worker is activated. Validate staged Liquidsoap configurations and retain previous versions for rollback, then restart `freo-playout@freo-demo` and `freo-playout@freo-demo-2` sequentially and confirm streaming recovery. Restart `freo`, `freo-ingest`, and `freo-automation` afterward. This briefly interrupts each demo stream and requires deployment approval. No database migration is needed.

Validation includes reference cleanup against PostgreSQL, cleanup failure/retry, browser menus and availability controls at desktop/mobile widths, and an isolated real-engine test for paused decks, current/future requests, carts, and repeated removal without skipping unrelated audio.

Deployment completed on 2026-09-19 after explicit approval. The database and prior engine configurations were backed up under `/var/backups/freo/music-20260919T172232Z`. `flask db upgrade` completed at `f38c6a902e17` (already the migration head). Both demo engines were validated, installed, restarted sequentially, and confirmed streaming. Web, ingest, automation, central API, microphone, and statistics services were restarted and active.

Live checks passed for `/health`, `/ready`, both authenticated music libraries and catalog APIs, both engine deletion commands, the song-editor availability layout, and public delivery of the changed JavaScript. No error-priority web, ingest, or automation journal entries appeared during deployment. “Phase 10 Test Cart,” “Phase 12 Block Item One,” and “Phase 12 Block Item Two” all completed processing after their source-file ownership was repaired.
