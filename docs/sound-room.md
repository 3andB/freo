# Sound Room and Music

Sound Room (`/admin/stations/<slug>/sound-room`) and the Songs tab of Music share the listening and organization workspace. Changes use existing station Song, Category, and MusicTag records. Category membership feeds the existing rotations; it does not specify playback order.

- Play before a song title starts private preview. The bottom player offers seeking, volume, and normalized/original listening. Only one preview plays at a time, and filters do not interrupt it.
- Select song checkboxes, then drag a song onto a category/tag or use Apply. A tag's grip can also be dragged onto a song. Touch users drag the grip; the rest of the row permits scrolling. Escape cancels a drag.
- Click a category name or chip to open its editor. Edit its name, description, and enabled state. Browse songs to add, or view current members and remove them. The stable category slug and ID remain unchanged.
- Create colored tags, rename them, apply to groups, and filter by them. Undo records only membership changes actually made, is station/operator scoped, single-use, and expires after one hour.
- Select a song for notes, processing, tags, categories, and analysis. Unsaved notes/category edits are protected during polling; notes detect conflicting saves.

## Analysis and loudness

The ingest worker processes explicit analysis requests first, then ingest jobs, then the unfinished accepted-song backlog, one at a time. ffmpeg runs at lower priority with a bounded timeout. Failure retries back off, stop after three attempts, and can be retried explicitly. Restart recovery restores interrupted work. Analysis validates finite LUFS/true-peak measurements and preserves manually entered cue points and notes. It does not enable songs.

Stations default to −16 LUFS. Sound Room can set the target between −30 and −12 LUFS. `gain_for` derives a fixed gain from measured integrated LUFS and limits boosts by the measured true peak (−1.5 dBTP ceiling) and a 12 dB maximum boost. Songs unable to reach the target are labeled Peak limited or Gain limited. Unanalyzed songs use unity gain and show Needs analysis. Originals are never rewritten.

The automation worker adds a bounded `freo_gain` annotation to music requests. Liquidsoap applies this gain before crossfading and a zero-makeup output limiter reduces overlap peaks. New targets affect newly queued songs, not already submitted requests. Browser previews use the same gain policy. This is overall song loudness matching, not constant momentary loudness; lossy encoding and overlapping music can alter final measured peaks. `test_loudness_playout.py` measures actual Liquidsoap output with differently leveled test signals.

## Permanent deletion

Music's song menu and the song edit page both expose explicit permanent-delete confirmation. The request removes broadcast eligibility and clears categories, tags, and cue selection. The storage-owning ingest worker then removes the original audio and private song-only artwork. A deletion status page confirms completion or failure. This cannot be undone.

Deletion is blocked for observed on-air/queued music, pending requests, active block items, direct Events/Blocks references, or running analysis. Running stations require a fresh playback observation. Historical song identity is retained for past play records, with `deleted_at` marking permanently removed media. The record is excluded from Music and its detail/audition routes; notes are erased. Shared album artwork may remain. A future intentional reimport is a new song.
