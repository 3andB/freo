# Playlists V1

Playlists replace the Sound Room navigation entry. The old Sound Room URL redirects to Playlists; Music retains private preview, tags, categories, processing, notes, and station loudness controls.

Every existing station receives empty **Playlist 1** and **Playlist 2** during migration. New stations receive them during creation. Owners can rename or delete these like any other playlist; deleted starters are not recreated.

## Owner workflow

1. Open **Playlists**, select a starter or click **New**, and save its name, description, and Straight or Random mode.
2. Choose **Add music**. Add individual songs, or copy the current songs from a category, artist, or album. Overlapping additions do not duplicate songs. Album additions respect disc and track numbers where present. Future library additions do not change the playlist.
3. Drag songs into order or use the up/down buttons. Remove individual or selected songs; Undo restores membership and order if the playlist has not changed again. Removal never deletes audio.
4. In **Music**, click song playlist bubbles to add/remove membership, apply a playlist to selected songs, or drag songs onto a playlist destination. Click the playlist name to open its editor.
5. In **Calendar → Add program**, select **A playlist**, choose the playlist, and set its time block.

Straight mode follows the saved order, then repeats; a new scheduled occurrence resets its position. Random mode chooses each playable song once per cycle before repeating, retaining its cycle across scheduled occurrences. With separation enabled, Straight mode advances to the next eligible song and Random mode selects from eligible remaining songs. Progress persists across automation worker restarts. Normal programming refresh replaces automatic lookahead without interrupting audio already playing.

Unavailable songs remain removable in the editor and are skipped during selection. An empty/unplayable playlist cannot be newly scheduled. If a scheduled playlist becomes unplayable, automation records the failure and uses the station default clock, or its active rotation; without either, the existing engine fallback applies. Program boundaries retain the existing finish-current-song behavior.

A scheduled playlist cannot be deleted until its schedule references are removed. Deleted playlist identities remain internally for historical clock references; audio is untouched.

## Phase 1: leaders and smart selection

The playlist editor offers an optional **Playlist leader** from available MUSIC or station-owned STATION audio. It plays once per existing schedule occurrence or explicit visual activation, ahead of normal membership. It does not consume a member position. Worker restart, queue refresh, shuffle-cycle rollover, and stop/resume within the same occurrence do not start another leader. A new occurrence starts a new leader even when it uses the same playlist. Leader decisions wait for confirmed playback before normal members are selected; failed queue submissions may retry. Reconciliation recovers accepted requests by their decision annotation after a select/push/commit crash. An absent untracked request must remain absent through a ten-second confirmation window before retry; incomplete engine inventory cannot prove failure. Pending leaders use the existing 250 ms worker cadence. If the leader is unavailable, history records `playlist_leader_unavailable` and selection continues without claiming it played. Re-enabling it takes effect at the next occurrence. Deleting the audio clears its leader references.

**Station music separation** configures artist and track windows in seconds, from 0 (off) through 86400. Category/rotation selection, ordinary playlists, visual music sources, and timed-event ONE/shuffled playlist selection share the policy. Confirmed start time is authoritative; selected, submitting, and queued music provide provisional holds. Failed decisions and other stations do not constrain selection. Artist names normalize case and whitespace; empty artist names do not group unrelated songs. If no candidate satisfies both windows, artist separation relaxes first, then track separation. `SelectionDecision.relaxation` records the result. Explicit leaders, manual cue choices, fixed event items, and Straight ALL event sequences retain their requested order. STATION and COMMERCIALS audio do not acquire music separation.

Enable **Choose songs dynamically from the library** to replace static membership at selection time with current MUSIC matches. Filters are ANDed; category/tag lists match any selected value. Artist, title, album, and genre are literal, case-insensitive substring filters. BPM, release year, and duration in milliseconds accept inclusive minimum/maximum bounds; missing metadata does not match a numeric bound. Blank filters include all available music. Station ownership, shared-library permissions, ingest acceptance, enabled state, deletion, and file checks still apply. Static membership is retained when turning dynamic mode off. A finite timed-event run freezes its matches when its existing execution snapshot is created.

Optional category/tag weights apply to Random selection within the current cycle, after separation. An unweighted song has weight 1; configured matching weights add together. Weights must be greater than zero and at most 100. They favor earlier selection without weakening the existing once-per-cycle guarantee; they do not impose a long-term play-frequency ratio. Straight ordering ignores weights. No configuration preserves existing selection behavior.

The existing playlist action API accepts `leader_track_id` (integer or null), `smart_enabled` (boolean), `smart_rules`, and `selection_weights`. Example rules: `{"genre":"jazz","bpm":{"min":90,"max":130},"release_year":{"min":1990},"tags":[3]}`. Example weights: `{"categories":{"2":4},"tags":{"3":2}}`. Tag/category IDs must belong to the station. Deleted tag/category filters remain visible as unavailable until explicitly removed; an unrelated edit cannot silently broaden the rules. Saving separation uses the existing CSRF-protected Music action endpoint with action `separation` and integer `artist_seconds`/`track_seconds`. All changes retain existing programming permissions, station locks, audit events, and playlist revision checks.

## Implementation and validation

`Playlist` stores station ownership, metadata, playback mode, and an internal edit-conflict counter. `PlaylistItem` enforces unique songs and ordered positions. `PlaylistCursor` stores progress per internal clock slot and schedule occurrence. Calendar playlist programs use internal single-slot clocks; V1 does not expose an Add Playlist Slot control in the show-template editor.

Mutations use the existing admin/CSRF boundary, station lock, audit log, and operator-scoped one-hour Music Undo. Shared tracks follow existing catalog availability rules. Playlist membership/configuration participates in programming signatures and cursor checkpoint/restore.

Tests cover snapshot additions, duplicate prevention, order and Undo conflicts, station isolation, deletion, default seeding, calendar validation, sequential/shuffle cycles, session restart, rehearsal, fallback patterns, and actual automatic-queue refresh. Browser tests exercise Music bubbles and dragging, editing, preview, removal/Undo, reordering, scheduling, and mobile width. The opt-in PostgreSQL tests cover migration upgrade/downgrade, starter backfill, and concurrent station creation.

## Rollout and fresh-VM validation

Phase 1 adds migration `f106a1b2c3d4` after `c83d4e5f9012`. It adds optional leader/configuration fields and an indexed decision occurrence key, preserving existing rows with disabled/empty defaults. Downgrading this revision removes Phase 1 configuration; retain a backup to restore it. The original playlist schema was introduced by `f73b8c9012ab`, after `a09f6d3e82b1`. PostgreSQL is required by the existing migration chain.

Before production rollout, review the migration and application diff together. Back up the database and use the installation's maintenance procedure to upgrade schema and restart web/automation processes on matching code. Do not run new code against the old schema.

On a fresh disposable VM using the normal installation procedure:

1. Install the prior revision, create a station with music and a scheduled category, then upgrade this revision and run `flask db upgrade`.
2. Confirm existing programming still works and exactly two empty starters appear for the station. Create another station and verify its starters.
3. Build and schedule a short playlist in both modes. Observe actual station audio and playback history through a block boundary and an automation restart.
4. Disable/remove playlist songs and verify fallback playback; restore songs and verify return to playlist selection.
5. Verify Music drag/drop and playlist controls at desktop and mobile widths.

Downgrade refuses to remove playlist schema while playlist clock slots exist. Remove playlist program clocks in a disposable environment before testing downgrade; deleting membership alone does not remove historical clock references. A database backup is the rollback path when retaining those references is required.
