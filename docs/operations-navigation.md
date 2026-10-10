# Radio Station Operations and station navigation

`/admin` is the installation-wide Overview. Its scope is always all stations,
including when an old bookmark contains `?station=...`. `/admin/stations` redirects
to the station-management section of Overview. Existing station detail URLs remain
available with station navigation.

The sidebar has an always-available Overview link followed by the station selector.
Changing the dropdown does not navigate. Switch submits to `/admin/switch-station`
and opens the selected station's Station Control. This works without JavaScript.
URLs determine the navigation scope, so direct links and browser history restore
the correct workspace. Overview displays operations links; station pages display
only that station's tools. Monitoring audio remains independent of navigation.

Operations links include statistics, the homepage editor, copyright reports,
player settings, listener feedback, installation/plan settings, and audit history.
Player Settings is a station directory. Its editing links open an explicitly named
station. Listener Feedback is an installation-wide, paginated inbox with station
and review-state filters. Its moderation forms use existing station-scoped POST
routes, CSRF checks, revision checks, and audit events.

## Overview observations

Overview and `/admin/api/operations` read local database observations. They do not
contact Icecast, Liquidsoap, or freo.live. The page refreshes observations every
15 seconds with a single bounded request; forms and keyboard focus are retained.

- Stream observations expire after 45 seconds (statistics collector) or 15 seconds
  (broadcast worker fallback).
- Current playback requires a successful worker observation within 10 seconds.
  Older confirmed starts are labeled as historical.
- Automation heartbeats expire after 15 seconds.
- A successful freo.live heartbeat within 65 minutes, with no current reporter
  error, establishes the connection badge. The reporter's hourly cadence includes
  retry/scheduling jitter. Older contact is labeled stale. Registration and plan
  entitlement do not by themselves imply a current connection.
- Synchronization compares each station's current metadata digest with the last
  successfully synchronized digest. The overview never exposes queued activation
  codes or installation credentials.
- Audience totals and concurrent peaks use the collector's installation scope,
  not a sum of station peaks. Overall storage uses the existing shared-media-aware
  installation inventory. Missing measurements display as unknown, not zero.

The summary reports a rolling 24-hour period. Full Operations Statistics provides
custom dates, comparisons, station breakdowns, audience/geography, confirmed plays,
feedback, transfer, storage, reliability, and CSV export using existing analytics.

## Validation and deployment

No schema migration, external API contract, or service configuration changes are
required. Restart the application workers using the normal release procedure.
On a fresh installation, check the empty-state Overview, create a station, start
the existing observation/reporting workers, verify live status and freo.live
contact, and switch between two stations. Stop a worker and verify stale states.

Focused tests are `tests/test_operations.py` and `tests/test_operations_browser.py`.
Browser tests use temporary databases and a loopback server. Existing navigation,
station lifecycle, forms, statistics, copyright, and installation tests cover
integration with the shared workspace.
