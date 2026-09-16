# Playlists V1

Playlists replace the Sound Room navigation entry. The old Sound Room URL redirects to Playlists; Music retains private preview, tags, categories, processing, notes, and station loudness controls.

Every existing station receives empty **Playlist 1** and **Playlist 2** during migration. New stations receive them during creation. Owners can rename or delete these like any other playlist; deleted starters are not recreated.

## Owner workflow

1. Open **Playlists**, select a starter or click **New**, and save its name, description, and Straight or Random mode.
2. Choose **Add music**. Add individual songs, or copy the current songs from a category, artist, or album. Overlapping additions do not duplicate songs. Album additions respect disc and track numbers where present. Future library additions do not change the playlist.
3. Drag songs into order or use the up/down buttons. Remove individual or selected songs; Undo restores membership and order if the playlist has not changed again. Removal never deletes audio.
4. In **Music**, click song playlist bubbles to add/remove membership, apply a playlist to selected songs, or drag songs onto a playlist destination. Click the playlist name to open its editor.
5. In **Calendar → Add program**, select **A playlist**, choose the playlist, and set its time block.

Straight mode follows the saved order, then repeats. Random mode chooses each playable song once per cycle before repeating; V1 does not add artist-separation rules or rearrange Straight mode. Each scheduled occurrence starts fresh. Progress persists across automation worker restarts. Normal programming refresh replaces automatic lookahead without interrupting audio already playing.

Unavailable songs remain removable in the editor and are skipped during selection. An empty/unplayable playlist cannot be newly scheduled. If a scheduled playlist becomes unplayable, automation records the failure and uses the station default clock, or its active rotation; without either, the existing engine fallback applies. Program boundaries retain the existing finish-current-song behavior.

A scheduled playlist cannot be deleted until its schedule references are removed. Deleted playlist identities remain internally for historical clock references; audio is untouched.

## Implementation and validation

`Playlist` stores station ownership, metadata, playback mode, and an internal edit-conflict counter. `PlaylistItem` enforces unique songs and ordered positions. `PlaylistCursor` stores progress per internal clock slot and schedule occurrence. Calendar playlist programs use internal single-slot clocks; V1 does not expose an Add Playlist Slot control in the show-template editor.

Mutations use the existing admin/CSRF boundary, station lock, audit log, and operator-scoped one-hour Music Undo. Shared tracks follow existing catalog availability rules. Playlist membership/configuration participates in programming signatures and cursor checkpoint/restore.

Tests cover snapshot additions, duplicate prevention, order and Undo conflicts, station isolation, deletion, default seeding, calendar validation, sequential/shuffle cycles, session restart, rehearsal, fallback patterns, and actual automatic-queue refresh. Browser tests exercise Music bubbles and dragging, editing, preview, removal/Undo, reordering, scheduling, and mobile width. The opt-in PostgreSQL tests cover migration upgrade/downgrade, starter backfill, and concurrent station creation.

## Rollout and fresh-VM validation

This change includes migration `f73b8c9012ab`, after `a09f6d3e82b1`. PostgreSQL is required by the existing migration chain.

Before production rollout, review the migration and application diff together. Back up the database and use the installation's maintenance procedure to upgrade schema and restart web/automation processes on matching code. Do not run new code against the old schema.

On a fresh disposable VM using the normal installation procedure:

1. Install the prior revision, create a station with music and a scheduled category, then upgrade this revision and run `flask db upgrade`.
2. Confirm existing programming still works and exactly two empty starters appear for the station. Create another station and verify its starters.
3. Build and schedule a short playlist in both modes. Observe actual station audio and playback history through a block boundary and an automation restart.
4. Disable/remove playlist songs and verify fallback playback; restore songs and verify return to playlist selection.
5. Verify Music drag/drop and playlist controls at desktop and mobile widths.

Downgrade refuses to remove playlist schema while playlist clock slots exist. Remove playlist program clocks in a disposable environment before testing downgrade; deleting membership alone does not remove historical clock references. A database backup is the rollback path when retaining those references is required.
