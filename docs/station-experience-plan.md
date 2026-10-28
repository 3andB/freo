# Station experience and scheduling redesign

Status: core implementation deployed and verified on 2026-09-15.

The later button-deck request supersedes the original crossfader design below: no broadcast slider or Playing Next in DJ; each deck provides Load, Play/Take Air, Pause, Stop/Clear, Fade, Repeat ×1 and private Preview. AUTO retains its queue.

## Delivered implementation

- Persistent MASTER MONITOR across internal navigation, explicit preview override, station switching, and custom dialogs.
- Independent button-controlled broadcast decks, paused-source resume, shared song/imaging carts with descriptions and ducking, and saved AUTO/DJ startup mode.
- Idle Deck A start and takeover fixes; delayed observations preserve display without stopping playback. Login initializes form tokens together to prevent navigation races.
- Calendar Day/Week/Agenda, weekly and date-specific programs, overnight blocks, category looping with existing separation rules, reusable clocks, event visibility, overlap validation and category dependency protection.
- Station identity editor with public URL aliases, modern overview/categories/decks, responsive shared UI, and public site with real demonstration screenshots.

## Remaining advanced scheduling work

The design below also specifies features beyond this implementation: immutable draft/publish revisions with undo, drag-resize and day/week duplication, full-day duration simulation and exact-end backtiming, configurable per-program exhaustion policies, commercial-capacity visualization, and cart queue cancellation. These are design commitments, not claims of shipped functionality. The current rehearsal uses the existing read-only selection preview; program boundaries finish the current item and clear obsolete lookahead.

## Validation

Core automated suite: 124 non-browser tests passed before final fixes. Final focused checks: 56 passed, plus the corrected station-mode fixture passed separately. Browser/station regression run: 26 passed, 1 optional screenshot test skipped; explicit screenshot and Sound Room run: 3 passed. Installed Liquidsoap proof passed pause, cart takeover/resume, and independent-deck mixing. PostgreSQL migrations passed full upgrade, downgrade to the previous revision and re-upgrade in an isolated database.

Deployment: database/config backup verified at `/var/backups/freo/station-experience-20260915T070649Z`; schema upgraded to `a57ce920bd31`. Both station configurations validated, preserving DJ_BOOTH for freo-demo and AUTO for the stopped freo-demo-2. Web, worker and running station services are active. Readiness/public routes returned HTTP 200, Icecast returned MP3 bytes, and the worker reported fresh DJ mixer state with no error and zero signal for the deliberately empty decks. No service errors appeared in the post-rollout journal check. Public layouts and images passed Chromium checks at desktop, tablet and mobile widths.


## Outcome

Make Freo a coherent radio workspace: one persistent listening control, reliable live decks, shared carts, and one calendar that explains what will play and why. Playback correctness comes before visual polish. All 20 requested changes are included below.

## Findings in the current code

- `app/static/live.js` explicitly rejects Deck A selection when `state.current` is absent. The service also requires an existing started decision for takeover. Removing only the browser message would leave the backend limitation.
- `set_mode()` in `app/services/live_assist.py` changes automation hold and currently requires automation to be enabled. Holding refill does not establish exclusive DJ ownership of the output.
- The Liquidsoap template has one request queue, generated-tone fallback, and a global three-second crossfade. Independent broadcast decks, continuous mixing, overlay ducking, and interrupted-track resume require engine work.
- Monitor audio belongs to the DJ page. The shared layout uses ordinary page navigation; preserving a preference alone cannot preserve the audio element across document replacement.
- `LiveCartSlot` references imaging only and has a label but no description, playback mode, or ducking setting.
- Scheduling already has weekly assignments, clocks, rotations, timed events, ordered blocks, traffic placement, and confirmed playback history. These are useful foundations for a unified planner.
- Station slugs currently also identify runtime files, private media directories, mounts, and services. Editing a name cannot safely rename all of these directly in a web request.
- The working tree contains substantial existing changes. Implementation must preserve and integrate those changes.

## 1. Playback contract and persistent monitoring

### MASTER MONITOR (request 1)

- Put MASTER MONITOR and the selected station name in the shared header, with volume and clear connecting, listening, off, and unavailable states.
- Active means actual browser playback: red with a slow pulse. Respect reduced-motion preferences; text and an accessible pressed state communicate the same information.
- Keep one audio controller above page content. Convert internal workspace navigation to replace content while retaining the shell, with history, back/forward, page initialization, and cleanup. Preserve it across internal public-site navigation where the same shell is used.
- Starting a local song preview, cue audition, or another local player stops MASTER MONITOR before that audio starts. Finishing a preview does not re-enable it. Broadcast transport changes do not themselves mute the operator's monitor.
- When the station selection changes, an active monitor reconnects to the newly selected station and updates its label. When off, it stays off.
- Sign-out stops protected previews and the monitor. Hard refreshes and external navigation create a new document; show a resume control if browser playback permission prevents restarting.
- Distinguish private listening volume from station broadcast gain everywhere.

### Authoritative AUTO / DJ control (requests 7, 8, 10, 11, 20)

- Introduce station output ownership and durable engine-confirmed deck state. Separate requested changes from observed changes; include a state revision and engine session identity in commands.
- Taking DJ control preserves the currently playing audio, including position, on Deck A. Deck B starts empty with a gentle cue-needed flash. If current output is imaging, preserve its identity too.
- DJ output consists solely of the decks and explicitly triggered carts. Empty or stopped decks produce silence. Suppress AUTO queue output, scheduled interruptions, active automatic block continuation, and generated-tone fallback while DJ owns the station.
- Freeze or invalidate automated lookahead during the handoff so it cannot unexpectedly reach air. Record interrupted blocks and missed scheduled items accurately.
- Loading either deck must work while the station is silent. Add a real start-from-idle command. A missing current decision must not be treated as proof of silence: reconcile fresh engine state, and display a specific unavailable-state error when the worker cannot observe it.
- Separate Load, Preview, Play, and Take Air. Repair Select to Air end to end: picker search, result selection, custom confirmation, command acknowledgment, and observed start.
- Taking DJ control must not depend on automatic music selection being enabled. Keep station-engine availability and permissions as separate checks.
- Returning to AUTO resolves the schedule for the current station-local time. It does not replay elapsed programming or drain obsolete requests. Default to a smooth handoff into current scheduled content; provide an explicit immediate handoff option.
- A closed browser does not silently switch DJ to AUTO. The engine continues its confirmed deck state and then silence if nothing else is running.
- Serialize conflicting operator commands, reject stale revisions, and show who has control. A second operator can explicitly take control through a custom dialog.

### Real broadcast mixer (requests 9, 13, 14)

- Extend the worker-controlled Liquidsoap graph with two independently controllable decks, an AUTO source, and a cart bus. The browser sends bounded control intent; the worker retains exclusive private-socket access.
- Provide a horizontal broadcast crossfader: left emphasizes A in orange-red, right emphasizes B in orange-red, center is green. Deck glow and a numeric contribution indicator follow confirmed gain.
- Use an equal-power curve with peak limiting. Center means both decks contribute; only a playing source can be audible. Keep gain contribution distinct from measured signal level.
- Synchronize the fader with engine acknowledgment, rate-limit drag updates, and reconcile after reconnection. Provide keyboard and touch operation.
- Show artwork, title, artist, elapsed/remaining time, spinning platter, measured levels, and clear LIVE / CUED / PAUSED / EMPTY states. Motion follows playback, never fabricated activity.
- AUTO uses one read-only animated deck with the same visual language and schedule context, without DJ transport controls.

## 2. Shared hot carts, station IDs, and sweepers (requests 5, 6, 12)

- Use one reusable cart bank in AUTO and DJ. Provide Hot Carts, Station IDs, and Sweepers sections with persistent station-scoped assignments.
- Assign an approved song or imaging asset through search, drag and drop, or a touch-friendly picker. Store a label, description, color, and playback behavior. Show unavailable assignments with a repair action.
- **PLAY OVER:** the main audio keeps progressing while the cart plays over it. A 0–100% reduction slider specifies how far to lower the main audio: 30% reduction leaves 70% of its prior gain. Preview that explanation beside the slider; restore the previous mix smoothly afterward.
- **TAKE OVER:** suspend the main program, play the cart, and resume from the interrupted position. In DJ mode preserve both deck positions and the fader; in AUTO preserve the interrupted program item and resume scheduling after it finishes.
- Default to one active cart. Additional triggers join a visible cart queue; allow cancelling queued carts and stopping the active cart. This prevents accidental stacked ducking.
- Mode changes during a cart cancel obsolete resume state and hand off to the newly chosen mode. An explicit stop or new deck selection must not resurrect an older interrupted source.
- Validate pause/resume and mixing with the installed engine before designing around them. Do not ship restart-from-beginning behavior labeled as resume.
- Record actual cart starts and completions with source, operator, mode, and interruption context.

## 3. One scheduling workspace (request 4)

### User model

Replace six competing planning destinations with **Schedule**. Its main views are Day, Week, and Agenda; reusable content lives in a side drawer. Mobile defaults to Agenda with a day picker.

The user starts with one of three actions:

1. **Play a category:** choose a category, start/end, repeat days, and playback rules.
2. **Build a show:** order songs, category picks, IDs, sweepers, breaks, and reusable sequences; repeat the sequence until the show ends if desired.
3. **Place an event:** schedule a song, ID, sequence, or commercial break at a time, with a clear timing rule.

Existing rotations become reusable selection patterns; clocks become show templates; blocks become sequences; timed events become calendar events; traffic becomes commercial planning inside Schedule. Preserve their underlying identities, history, and advanced controls during migration.

### Calendar behavior

- Drag to create or resize a time block; duplicate a day or week; save a show template; drag content into a block. Every gesture has equivalent buttons and editable fields.
- Support bounded blocks, overnight shows, weekly recurrence, date exceptions, one-off overrides, and station timezone/DST explanations.
- Use separate lanes for programs and timed events, plus commercial-break markers. Show gaps, conflicts, the live time marker, and current output ownership.
- Publish drafts as immutable schedule revisions. Preview the changes, affected future airplay, missing audio, timing issues, and commercial capacity before publishing. An undo action creates a new revision without rewriting history.
- Day-only edits offer “this occurrence” versus “the recurring series.” Concurrent editors get an explicit conflict instead of overwriting each other.

### Resolution and timing

- DJ ownership has priority over automated scheduling. In AUTO, date-specific programs override weekly programs; uncovered time uses the configured station default. Reject ambiguous overlaps at the same priority.
- Every boundary has a plain-language policy: finish the current item, fade at the boundary, or aim to finish exactly using duration-aware selection. Explain that a soft boundary can run late.
- Timed events have explicit interruptibility, late window, and missed-event behavior. Reject incompatible simultaneous hard events before publishing.
- Resolve events on the server in UTC while presenting station-local time. Define skipped/repeated DST-time behavior consistently across weekly and one-off items and expose it in previews.
- Returning from DJ resumes the active program now. Expired events are recorded as missed unless their configured grace window permits delivery.

### Intelligent looping

- A category block continuously chooses eligible tracks until its boundary. A show can loop its ordered pattern, repeat a fixed count, or run once.
- Preserve a durable cursor and occurrence identity across worker restarts. Keep pending selections separate from confirmed starts.
- Enforce track and artist separation, category weights, availability, explicit-content restrictions where configured, and imaging spacing.
- Before a fixed boundary, look ahead using measured durations to choose a fitting ending or approved short filler. Account for fades and carts. Show when an exact finish is infeasible; do not promise exact timing from estimates.
- Give each program an explicit exhaustion policy: alternate category, approved filler, relax specified separation rules in a displayed order, or silence. Never silently choose unrelated music.
- Prevent endless scans with bounded candidate searches, then report the reason for the fallback.
- Replan uncommitted future selections when content becomes unavailable. Preserve the currently playing item and confirmed history.

### Distinctive planning tools

- **Explain this play:** each projected selection shows its category or pattern, eligibility reasoning, repetition constraints, and any relaxed rule.
- **Rehearse the day:** run a read-only simulation showing likely timing, repetitions, gaps, late events, and commercial capacity. Label forecast selections as estimates.
- **Coverage ribbon:** show continuous planned coverage and unresolved problems above the calendar, including fallback-filled gaps.
- **Live versus planned:** compare actual starts with the published day, including DJ overrides, missed breaks, and return-to-AUTO position.
- Preserve traffic's campaign rules, locked finalized placements, actual-airplay reconciliation, and makegood links within this unified view.

### Suggested implementation structure

Add calendar program definitions, recurrence exceptions, schedule revisions, timing/loop policies, and an occurrence resolver. Adapt existing clock/category/rotation/event/block services behind one planning API. Use one executor and one confirmed-airplay ledger; avoid creating a second scheduler that competes with the worker.

## 4. Station editing (request 3)

- Add a station editor for name, description, public URL slug, timezone, and visual identity. Generate a suggested slug from the name and show the resulting URLs before saving; allow an explicit custom slug.
- Separate stable internal station/runtime identity from editable public URL identity. Existing private media paths, service identifiers, and history retain stable references.
- Update station listings, player links, header labels, stream metadata, and public routes coherently. Retain previous public URLs as aliases so existing listeners and embeds keep working.
- Apply any required proxy or engine metadata updates through a narrowly scoped validated provisioning operation, with pending/applied/failed state and rollback. Web requests must not directly rename runtime files or run arbitrary service commands.
- Validate reserved names and collisions; timezone changes show their effect on scheduled wall times.

## 5. Modern interface and categories (requests 2, 15, 16, 17, 18)

- Establish shared typography, spacing, surfaces, forms, buttons, status colors, tables, drawers, notifications, and custom dialogs before applying page redesigns.
- Overview prioritizes actual current audio, AUTO/DJ ownership, monitor, next program, schedule coverage, and actions to resolve actionable issues. Show stale observations explicitly.
- Categories use searchable cards with color, description, track count, duration, and schedule usage. A split editor supports search, multi-select, drag/drop membership, and bulk add/remove with touch and keyboard alternatives.
- Category deletion never deletes songs. Show all direct and indirect schedule/template dependencies before deletion; offer replace references, remove affected rules with validation, or cancel. Retain historical labels and snapshots. Published revisions must not be left with dangling references.
- Replace JavaScript alert/confirm/prompt calls and native form-validation bubbles with styled application feedback. Custom dialogs explain consequences, offer clear actions, retain input on failure, manage focus, and support Escape where safe.
- Apply the shared system to music, Sound Room, imaging, stations, planning, logs, settings, uploads, login, and error/empty/loading states.
- Design desktop, tablet, and mobile layouts explicitly: stacked decks, usable fader, reachable cart controls, agenda calendar, responsive tables, visible focus, and no hover-only controls.

## 6. Public website (request 19)

- Rebuild the homepage around a clear station-creation story, real product screenshots, a DJ Booth feature section, the visual schedule, and an obvious entry to station operation.
- Capture screenshots from the completed UI using seeded demonstration content; exclude real account data and private details.
- Modernize station listings and public players using the shared visual system, responsive artwork, clear listening status, and accessible playback controls.
- Optimize screenshot sizes and provide meaningful alternative text. Public copy describes features that have actually shipped.

## Delivery sequence and exit criteria

| Phase | Deliverables | Exit condition |
| --- | --- | --- |
| 1. Playback foundation | Reproduce reported failures; establish engine ownership, deck protocol, start-from-idle, handoffs, and a two-deck/cart engine proof | Captured output proves DJ exclusivity, silence, uninterrupted A handoff, mixer gains, cart resume, and AUTO recovery |
| 2. Shared shell and controls | Persistent monitor, navigation lifecycle, design tokens, custom dialogs, station context | Monitor survives internal navigation and stops for previews without automatically resuming; station switching is consistent |
| 3. DJ and carts | Repair pickers/assignment, real fader, deck visuals, cart descriptions and both playback behaviors, AUTO deck | User can start from silence, perform a two-deck set, trigger carts in either mode, and return to the schedule |
| 4. Scheduling core | Unified resolver, bounded programs, recurrence exceptions, loop policies, revisions, migration adapters | Existing schedules preserve behavior; new resolver passes deterministic timing, restart, DST, exhaustion, and override cases |
| 5. Scheduling workspace | Calendar, templates, category blocks, commercial planning, rehearsal, explanations | A user can create and publish a complete week from categories without understanding clocks or rotations |
| 6. Station and library UX | Station editor/URL aliases, category management, overview and remaining admin screens | Metadata edits propagate; old public links work; category deletion preserves tracks and protects schedule integrity |
| 7. Public site and release | Actual screenshots, responsive polish, end-to-end checks, migration rehearsal, operator documentation | Desktop/tablet/mobile acceptance and staged runtime checks pass; release has a tested rollback path |

## Verification and rollout

- Add focused service tests for command revisions, conflicting operators, station isolation, idle starts, deck ownership, schedule resume, cart state restoration, deletion dependencies, and URL collisions/aliases.
- Extend existing browser suites for picker failures, descriptions, assignment, custom dialogs, monitor navigation, back/forward cleanup, touch interactions, fader keyboard operation, and responsive layouts.
- Use short distinguishable test tones/audio in an isolated station to measure actual output: crossfade contribution, ducking percentage, cart resume position, silent DJ state, and scheduled interruption suppression. UI success alone is insufficient.
- Exercise worker and engine restarts, stale observations, duplicate commands, delayed acknowledgments, media failure, and cart/mode races without replaying destructive commands.
- Run schedule simulations for overnight periods, DST gaps/repeated times, conflicting events, exhausted categories, fixed boundaries, and finalized traffic reconciliation.
- Migrate additively, compare old/new schedule resolutions, and retain old published history. Rehearse database and engine configuration rollback before a production handoff.
- Release engine capabilities per station behind capability checks; controls stay unavailable with a clear reason until the matching engine version is ready.

## Default interpretations

- MASTER MONITOR is private listening; DJ transport and fader control the actual broadcast.
- TAKE OVER carts resume the interrupted position, rather than restarting the song.
- DJ ownership suppresses all automatic interruptions, including IDs and commercials; the planner records misses.
- Active monitoring follows a change of selected station.
- Public URLs track edited public identity while older URLs remain usable.
- These defaults make implementation concrete and can be adjusted without changing the overall delivery order.
