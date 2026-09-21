# First-use license agreement

On the first authenticated admin page, Freo displays a license agreement popup.
Each administrator must check the acknowledgment and select **Accept and continue**,
or select **Decline and sign out**. The copyright restriction is displayed in bold:

**You may not broadcast copyrighted material without permission. Doing so is a direct violation of this license.**

The agreement uses the published [Freo Live licensing information](https://freo.live/licensing),
reviewed on September 21, 2026, and the explicit copyright restriction above.
That website describes installation entitlements and broadcasting responsibilities;
it refers source-code terms to the repository. This feature does not select a
source-code license.

Acceptance is stored per administrator and agreement version in `audit_events`,
including the acceptance time. It survives logout, browser changes and restarts.
Existing administrators see the agreement the next time they open an admin page.
Public listeners do not see it. **License agreement** at the bottom of Station
Control reopens the same text without requiring another acceptance.

The popup is an admin UI acknowledgment, not a broadcast-engine or API authorization
gate. Existing broadcasts continue. No schema migration or external request is
needed to display or accept the bundled agreement.

When changing the terms in `app/templates/admin/_license_agreement.html`, update
`AGREEMENT_VERSION` in `app/services/license_agreement.py` to request fresh acceptance.
