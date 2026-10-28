# Public listing and now-playing sharing

RC16 implements the optional now-playing capability in the Freo reporting API
2026-10-v1.3 documentation: https://freo.live/downloads/freo-api/2026-10-v1.3/contract.md.
The ordinary reporting wire revision remains 2026-10-v1.1.

Each station has one setting: “List my station on freo.live and share what’s playing.”
It publishes the station name, canonical website/player URL, current song and artist.
New stations default ON. An explicit OFF keeps a station private without stopping
its private telemetry or broadcasting.

On upgrade, existing ON choices remain ON. Legacy OFF values with a recorded
station-details save remain OFF conservatively: older versions did not record the
checkbox choice separately. Other legacy defaults become ON. The migration stores
provenance, preserves permanent identities, and forces metadata reconciliation.
Subsequent explicit choices are recorded and never overridden by a default.

The single, locked central reporter syncs consent and public URLs. It checks for
changes every five seconds, independent of hourly telemetry. Turning OFF suppresses
new song reports immediately locally; the worker prioritizes syncing OFF and retries
withdrawal if the API is unavailable. Remote live claims expire within three minutes;
the All listed entry remains until withdrawal is acknowledged.

A successful health response must advertise X-Freo-Now-Playing-Revision: 2026-10-v1.
Without support, only optional song reporting pauses. The worker samples confirmed
final-output state, not previews or queued songs. Audible DJ overlaps select the
highest-gain source, breaking ties by the latest start. Missing metadata is null;
no display placeholder is reported as a song. Unknown broadcast status is withheld.
Confirmed off-air status clears metadata. Observation timestamps are sampling times.

Changes are sent promptly; healthy long-track refreshes are scheduled after 50
seconds, leaving polling headroom within the 60-second requirement. Requests batch
up to 100 channels and 256 KiB. A separate allowance of 60 requests per rolling
minute leaves headroom under the API's shared IP authentication protection.
Retries resample current state with 5-to-60-second bounded backoff and jitter,
honoring longer Retry-After responses. No historical song queue is stored.

A 409 invalidates the affected batch's sync acknowledgements and reconciles current
consent before retry. A 401 preserves credentials and identity and requires operator
attention. Missing capability and 404/405 pause the optional feature; health is
rechecked after restart/rejection and hourly. HTTPS verifies certificates, does not
follow redirects, and bounds connections at five seconds and now-playing responses
at ten seconds. All network work is outside playout and web requests.

The installation page displays capability, last accepted song report and pending
sync/reporting errors. Reporting never changes licensing, entitlement, audio intent
or station identity.
