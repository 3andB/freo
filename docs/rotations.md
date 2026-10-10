# Categories and explicit rotations

Categories belong to one station and have unique station-local slugs. Tracks may belong to several categories but are never duplicated in storage. Only accepted, enabled tracks with a regular approved file can be selected. A disabled category supplies no future requests. Names are display text; slugs use the same conservative ASCII validation as stations.

A rotation is an ordered, repeating sequence of category slots. Freo Demo's test sequence is `Power, Medium, Power, Gold, Power, Medium`. The database stores one active rotation and a durable next-slot cursor per station. This is a manual mode choice, not a clock or schedule. Empty or disabled slots are audited and skipped up to one full cycle; if none can supply media, Liquidsoap keeps the fallback tone. Enabling/disabling slots is atomic at the database level; the selector normalizes the cursor against the currently enabled sequence.

The selector locks the station's automation state row in PostgreSQL while choosing and advancing its cursor. It filters station ownership, media status, enabled flags, file existence, and separation windows. Among eligible tracks, it chooses the least recently started; never-played tracks sort first, then stable ID order breaks ties. Pending selections are temporary holds so the small lookahead queue does not immediately repeat a track. Artist keys use Unicode case folding and collapsed whitespace. If strict track and artist separation leaves no candidate, Freo first relaxes artist separation, then track separation. Every relaxation and empty-slot skip is recorded on a decision. Defaults for both windows are zero; the operator configures values appropriate to the library. Album separation is deferred.

Root-run CLI examples from `/opt/freo`:

```text
venv/bin/flask --app wsgi:app category create --station freo-demo --name Power --slug power
venv/bin/flask --app wsgi:app category assign --station freo-demo --track TRACK_UUID --category power
venv/bin/flask --app wsgi:app rotation create --station freo-demo --name Main --slug main
venv/bin/flask --app wsgi:app rotation add-slot --station freo-demo --rotation main --category power
venv/bin/flask --app wsgi:app rotation activate --station freo-demo main
venv/bin/flask --app wsgi:app rotation preview --station freo-demo --count 20
venv/bin/flask --app wsgi:app automation enable --station freo-demo --track-separation 1800 --artist-separation 900
```

Preview simulates selections without advancing the cursor or writing history. `rotation show`, `rotation list`, `rotation enable-slot`, `rotation disable-slot`, `category list`, `category enable`, `category disable`, `category unassign`, `automation status`, and `automation explain` support routine administration. No category or rotation mutation is available through the public API. Public read-only category, rotation, automation status, and started-history endpoints live under `/api/stations/<slug>/`.
# Clocks above rotations

A Phase 6 clock may reference a rotation in an ordered programming slot. That slot advances the rotation's category cursor and uses the existing separation rules. The clock cursor is distinct, so clocks can also alternate direct category requests with rotation requests. See [clocks](clocks.md).

Browser programming controls are documented in [programming UI](programming-ui.md). The root CLI remains available for recovery.
