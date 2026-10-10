# Event blocks and stopsets

An event block is a station-scoped ordered sequence of approved Tracks and ImagingAssets. `GENERIC`, `STOPSET`, `NEWS`, `LEGAL_ID`, `PROMO_BLOCK`, and `SPECIAL` describe its purpose; they do not select different execution code. `COMMERCIAL` is an imaging classification only and does not provide traffic, billing, contract, or affidavit behavior.

Blocks are created as disabled drafts. Every enabled item must resolve to enabled, accepted, contained media before the block can be enabled. Total duration is derived from item durations. Items inherit `SKIP_FAILED_ITEM` or `ABORT_BLOCK` unless they carry an override.

Freo snapshots enabled item identities, positions, labels, and failure policies into durable execution rows. Later edits affect future runs only. The worker submits the snapshot in order with small lookahead and suppresses normal refill while it is active. Confirmed Liquidsoap starts establish item and block start. Tracks affect later track and artist separation; imaging affects imaging recurrence. Block items never consume music rotation positions.

A timed event can target a block. Event timing and missed policy govern the start of item one; internal failures use block policy. A hard event offset is the confirmed start of item one. A clock can use an `EVENT_BLOCK` slot and advances once when it creates the execution. Live Assist can queue a block and display active progress. Abort Block is worker-mediated and uses a fixed allowlisted queue operation. Automation Hold does not freeze an active block.

The browser never supplies a file path or Liquidsoap command. All content is looked up again by station. The web process writes definitions and intent to PostgreSQL; the automation worker alone uses the private station socket. PostgreSQL backups include block definitions and execution history.

```text
flask block list --station freo-demo
flask block create --station freo-demo --name "Top of Hour" --type stopset
flask block add --station freo-demo --block top-of-hour --kind imaging --content <asset-uuid>
flask block validate --station freo-demo top-of-hour
flask block enable --station freo-demo top-of-hour
```

Phase 12 plays items sequentially. It does not mix sweepers, manage advertisers, rotate spots, produce billing, switch live sources, or provide traffic reconciliation.
