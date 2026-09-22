# First-use license agreement

On the first authenticated admin page, Freo displays a license agreement popup.
Each administrator must check the acknowledgment and select **Accept and continue**,
or select **Decline and sign out**. The copyright restriction is displayed in bold:

**You may not broadcast copyrighted material without permission. Doing so is a direct violation of this license.**

The agreement reflects the bundled [Freo Source-Available License](../LICENSE):
three free stations total per owner, with a US$99 perpetual owner-wide unlimited
license above that allowance. All future updates are included. Registration is
optional, cross-installation counting is honor-based, and paid activation works
offline. Purchase starts by contacting info@3andB.com for an emailed Stripe invoice.

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
