# Traffic and commercial delivery

Traffic plans commercial inventory; EventBlock executes finalized stopsets; Liquidsoap plays approved ImagingAssets; confirmed playback reconciles delivery. Traffic never enqueues audio directly and does not duplicate ingestion, storage, probing, or queue control.

Advertisers and campaigns are station scoped. Active campaign rules describe weekdays, station-local dayparts, requested daily spots, and minimum separation. Enabled `COMMERCIAL` ImagingAssets attach as creatives. The deterministic generator allocates higher priority campaigns first, spreads spots across eligible stopsets, rejects campaign duplication within a break, uses actual duration, and reports unscheduled demand rather than breaking capacity or separation.

TrafficStopset templates contain fixed imaging and non-playable commercial inventory slots. A generated log is a preview and does not affect air. Explicit finalization freezes placement display snapshots, creates an exact materialized EventBlock for each populated break, and schedules it through TimedEvent. Placeholders never reach Liquidsoap.

Only the existing Liquidsoap confirmation callback marks a placement AIRED and records actual UTC start. Failed or skipped item executions reconcile as FAILED or MISSED. The original miss remains intact; a separate placement can reference it as a makegood. Finalized and reconciled logs cannot be regenerated.

The authenticated Traffic workspace supports advertiser contact/reference edits and disable, campaign edits and lifecycle status, creative and rule enable/disable, stopset enable/disable, daily generation, explicit finalization, and CSV export. Opening a draft log exposes placement moves, creative substitutions within the same campaign, and removal. Every draft adjustment repeats capacity, inventory, daypart, separation, campaign-collision, and station ownership checks on the server. Finalized and reconciled views replace those controls with a locked indicator.

The log detail page is also the reconciliation record: it displays station-local scheduled and actual times, immutable advertiser/campaign/creative snapshots, delivery status, failure reason, and makegood linkage. A MISSED or FAILED placement can be scheduled into a separate future draft log. The original historical placement remains unchanged, and the target stopset is fully revalidated before the makegood is accepted.

```text
flask traffic generate --station freo-demo --date 2026-09-15
flask traffic show --station freo-demo --date 2026-09-15
flask traffic finalize --station freo-demo --date 2026-09-15
flask traffic reconcile --station freo-demo --date 2026-09-15
```

Phase 13 does not calculate rates, commissions, invoices, pacing, or affidavits.
