Scheduling and Events: completion and activation notes

This change completes the code work identified in the [19 September review](events-review-plan-2026-09-19.md). It builds on the existing unified audio and Events implementation. **Activated on 19 September 2026**, following explicit authorization to migrate, restart, commit and push. Implementation was first validated in isolation; the live activation results are recorded below. Deployment statements in the [earlier release notes](events-station-commercials-release.md) describe that earlier release only.

**Operator behavior**

- New stations receive Playlist 1, Playlist 2, STATION and COMMERCIALS in that order. STATION and COMMERCIALS are persistent default collections, automatically populated by audio classification. The first two remain editable and deletable. Custom playlists retain their contents and identity.
- Classify station IDs, promos, announcements and similar audio as STATION; `station_id` remains an audio subtype, separate from the database field identifying the owning station. Classify advertising audio as COMMERCIALS. The existing upload, edit and bulk classification workflows manage membership.
- Imaging no longer appears in live carts, audio discovery, clock creation or block creation. Compatibility inputs must resolve to an already migrated catalog track or fail with a migration message. New Events, blocks, carts and traffic references use catalog audio. Historical models, original files and conversion mappings remain available for upgrades and history.
- Events can select a playlist, individual audio or a sequence. STATION defaults to one rotating item; COMMERCIALS defaults to the entire selected playlist once. Users can change that choice or select a custom subset. Each execution freezes its item order.
- New browser events wait until the current song ends. INTERRUPT DJ defaults to No. Yes allows a handoff after the audible song, including automatic audio playing during DJ standby. Live microphones remain protected. Existing explicitly labelled legacy timing policies remain unchanged until converted in the editor.
- One-time, every 15 minutes, hourly, daily, weekly and monthly schedules share validation between saving and previewing. Hidden controls cannot invalidate an unrelated recurrence. Preview returns the next ten available runs, including distant one-time dates and sparse monthly rules, or explains that no more runs exist.
- All Events input and presentation use the station timezone in Settings. Lists and history include local dates, seconds and UTC offsets. Changing timezone preserves future local wall times, rebuilds unstarted occurrences and leaves historical instants intact. Missing monthly dates are skipped; daylight-saving gaps move forward by the gap, and repeated local times run once at the first occurrence.
- Audio search prioritizes the STATION and COMMERCIALS defaults, then other playlists and individual audio. It supports classification filters, sequences, title, artist, album, filename, subtype, cart code and tags. Search within a playlist has a visible scope; results include availability, counts and duration. Playlist totals use grouped queries instead of loading every result's items.

The changed Events, playlists and live-control scripts have versioned asset URLs so cached scripts cannot delay activation of the new behavior.

**Execution changes**

The engine reserves boundaries across automatic audio, DJ decks and mode changes. Pause, clear, deck takeover and cart playback have explicit handoff behavior. Events insert ahead of future ordinary queued audio while preserving that audio's relative order.

The worker expires stale unreserved occurrences independently of its candidate-page limit. PostgreSQL advisory ownership prevents two normal worker processes from filling the installation's engines simultaneously. Concurrent edits and cancellation serialize on the station record. Cancellation removes the event's future requests, including requests whose socket acceptance response was lost, without flushing unrelated music.

Execution history distinguishes complete, partial and entirely failed sequences. Engine restart marks interrupted event execution failed while preserving confirmed starts as airplay history; later worker passes cannot resurrect the failed occurrence from that historical start. Timed audio requires completion evidence. When its request is absent from a complete engine inventory beyond the duration plus a recovery margin, a missing END records failure instead of treating elapsed duration as proof of completion. Paused requests retained by the engine remain protected. Aborting a sequence removes future items and lets the active item finish.

**Migration review**

New revision `f38c6a902e17` follows `e28a91bc7304`. It adds no columns and moves no audio. It assigns stable starter keys only when a station's original leading pair still has the exact names Playlist 1 and Playlist 2 and neither row already has a key. Renamed or ambiguous legacy playlists are deliberately not adopted; their origin must be reviewed separately if restoring the four-default order is desired. New stations have explicit starter identities from creation.

The migration changes only `system_key` metadata. Its downgrade clears the two starter keys. Existing STATION/COMMERCIALS classification, identities and contents are preserved. SQLite and disposable PostgreSQL tests exercise upgrade behavior and preservation of custom/renamed playlists.

**Activation procedure**

1. Record the installed revision, station list and desired states. Back up the application revision, database, media and current rendered engine configurations together. Rehearse this procedure in a test installation before broadcast use.
2. Run `venv/bin/flask --app app migrate-station-audio --station SLUG` for each station to inventory remaining legacy audio and references. If conversion is still required, follow the stopped-station, file-verification and resumable `--apply` procedure in the earlier release notes. Do not reactivate disabled or rejected audio. Inventory again and resolve any remaining active references before reopening affected workflows.
3. In a coordinated maintenance window, stop worker/web activity that can mutate scheduling, install this code and apply `venv/bin/flask --app app db upgrade`. Confirm the migration head is `f38c6a902e17` and inspect default ordering on each station. Do not infer renamed legacy starter identity from a matching display name elsewhere.
4. Render each station with `venv/bin/flask --app app station render SLUG`. Validate the generated configuration and restart the station engines and application services through the normal operations procedure. Keep the application, worker and rendered engine template at the same release. Start only one automation worker; confirm its heartbeat and the event protocol after restart.
5. On a controlled station, verify a STATION item and a finite COMMERCIALS sequence after a current song, return to programming, DJ No/Yes behavior, cancellation, and local-time previews. Verify future queued music remains ordered and history reports actual starts/completion. Check health/readiness and station output before normal operation.

For rollback of this revision alone, stop scheduling activity, restore the paired application/engine release and use `venv/bin/flask --app app db downgrade e28a91bc7304` if starter metadata must also be reverted. If legacy Imaging conversion was applied during the same maintenance window, use the coordinated database/media/application/engine backup restoration procedure instead; a metadata downgrade does not reverse that conversion.

**Fresh-VM validation plan**

Provision a clean supported VM using the documented installer, create two stations and inspect all four defaults. Import temporary music, a station ID and commercials; verify station isolation, classification and fallback exclusion. Create/save/reload all six event recurrences with a station timezone different from the VM and browser. Exercise the controlled playback checks above, then reboot and confirm worker ownership, station readiness and event recovery.

Separately restore a pre-upgrade fixture with custom playlists and legacy Imaging references, rehearse inventory/conversion/upgrade, rerun conversion to establish idempotence, and verify historical references and disabled states. Exercise metadata-only rollback and backup restoration. Fresh-VM provisioning has not been performed; verification of this existing installation is recorded below.

**Validation**

- Focused SQLite service/route regressions: **124 passed**.
- Follow-up worker/Events regressions after the restart and missing-END fixes: **78 passed**. These cover the final worker changes, including preservation of failed history across later scheduling passes.
- Events and playlists browser workflows: **4 passed**, including save/reload of all six recurrences and search within a playlist.
- Isolated Liquidsoap event recordings: **12 passed**, covering after-song automatic insertion, decks A/B, DJ standby automatic audio, pause, clear, mode change, and overlay/takeover carts.
- Disposable PostgreSQL scheduling/Events checks: **5 passed**, including migrations, concurrent edits, stale backlog and worker ownership. An earlier combined station/scheduling/Events run also passed all **8** tests.
- Repository-wide suite: **741 passed, 50 skipped, 5 failed** in 43 minutes. All five failed cases subsequently passed after the test corrections described below. The entire suite was not restarted after those corrections.
- Final Events/live/playlists route checks after asset versioning: **3 passed**. Python compilation, JavaScript syntax checks and `git diff --check` passed.

The full run exposed an outdated master-broadcast migration fixture, two native clicks obscured by fixed UI controls, a no-JavaScript status read racing document navigation, and a weekday test that deselected the days it intended to schedule. The migration test now round-trips its own revision; the browser tests scroll before native clicks, wait for the new document, and explicitly select Monday/Wednesday/Friday. The corrected master-broadcast group passed all **9** tests, the music-tags and scheduling-studio browser cases each passed, and the final weekly Events/native-navigation browser run passed both **2** tests. The Operations browser group also passed all **4** tests during diagnosis. No unrelated product behavior was changed to satisfy these tests.

The repository-wide run used a frozen temporary source copy so ongoing edits could not mix old Python modules with changed templates. Final worker recovery changes were verified by the separate 78-test run; subsequent template/version changes and the five test corrections were verified by the targeted runs above. Counts overlap and should not be added as unique tests. The broad run's skips include opt-in engine, PostgreSQL and scale checks; the relevant dedicated engine and PostgreSQL results are listed separately.

Tests use temporary media, databases and engine configurations with `FREO_ENV_FILE=/dev/null`. Known warnings are the existing playlist fixture's SQLAlchemy session warning and the migration tooling's deprecated `get_engine` API. The results above describe isolated tests; live verification follows.

**Live activation — 19 September 2026**

- Backup: `/var/backups/freo/events-completion-20260919T041429Z`. Contains a verified custom-format PostgreSQL dump taken with application writers paused, media/configuration archive, prior committed source, and original station/service states. Backup access is restricted to root.
- Rehearsed upgrade → downgrade to `e28a91bc7304` → upgrade on a temporary PostgreSQL database restored from that backup. All steps passed and the disposable database was removed.
- Applied `f38c6a902e17` to the live database. Both stations now have stable Playlist 1, Playlist 2, STATION and COMMERCIALS identities in that order.
- Inventory confirmed five previously converted legacy assets on Freo Demo, none on Freo Demo Two, zero remaining legacy references, no file problems and no pending ingest jobs. No additional audio conversion was needed.
- Rendered and validated both managed Liquidsoap configurations. Restarted web, automation, ingest, microphone, central API, statistics, diagnostic playout, both managed station engines, Icecast and Nginx. Resumed all previously active maintenance timers. Application and station services became active at 04:17:37 UTC.
- Both stations retained running/AUTO state and their Settings timezones: America/Denver for Freo Demo and UTC for Freo Demo Two.
- Verified health/readiness, automation and Icecast health, public HTTPS, authenticated Events/create/playlists/live pages, Imaging redirects, prioritized audio search, and ten-run monthly previews in station local time. Public Events/playlists/live scripts matched the deployed source bytes.
- Both managed engines answered the Events protocol and delivered 8,192 MP3 bytes each. Worker heartbeats were under four seconds old. Restart counters were zero and no failed systemd units remained.
- `scripts/validate-install.sh` passed. Disabled station IDs and commercials were not enabled or aired as part of deployment verification; the finite sequence and after-song behavior were validated by the isolated engine tests above.
