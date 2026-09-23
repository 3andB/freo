# freo.live team: distribution handoff

Status: candidate prepared for separate-VM acceptance, not approved for public
release. The software repository is **https://github.com/3andB/freo**. The
freo.live website/API is separately managed; this repository does not deploy it.

## Pages and copy to implement

Use 3andB as publisher and licensor. Add a quiet About/footer credit:
“Created by Lee Eyerman.” Link the repository's LICENSE. Describe the product
as **source-available**, not OSI open source.

Pricing copy:

> Free for up to three stations total across all installations you own, including
> commercial use. Need more? Pay US$99 once for unlimited stations across all your
> installations, with all future updates included. Registration is optional and
> the combined station allowance is honor-based. Paid licenses work offline.

The purchase button should link to
`mailto:info@3andB.com?subject=Freo%20unlimited%20license`.
Explain: “Contact us and we will email a Stripe invoice. After payment, we will
send your license file.” Do not require an account or build an automated checkout
for this initial release. Do not imply $99 per server, per station, per year or
only for commercial use. There is no recurring license renewal.

Create/update the download page, pricing/licensing page, installation guide and
upgrade/recovery guide. On downloads show version, release date, Ubuntu 24.04
x86_64, archive size, SHA-256, release notes, GitHub source link, detached signature
and trusted publisher public key/fingerprint. Link the exact versioned artifact,
never a mutable branch ZIP. Include the telemetry disclosure from the installation
guide. Separate fresh installation from upgrades; never instruct an existing
user to rerun the installer or replace their database.

Use [install-candidate.md](install-candidate.md) as the current operator guide.
Fresh rc.5 installs automatically create `admin` / `IAmOnTheAir` for first-use
setup. Require a new password before administration; remove the old first-admin
CLI instruction from website copy. The initial account is never recreated by upgrades.
After VM acceptance and owner approval, adapt candidate wording to the approved
version while preserving verification, recovery and platform instructions.
License terms are in [LICENSE](../LICENSE). Technical privacy/reporting details
are in [central-api-integration-plan.md](central-api-integration-plan.md).

## Release assets and API

Each owner-approved GitHub Release must contain:

- The exact tested `freo-vVERSION.tar.gz` (code, migrations, operational tools,
  public license verification key, dependency wheels and hash lock).
- `freo-vVERSION.tar.gz.asc`, `publisher.gpg`, `SHA256SUMS`, and release notes.
- `latest.json` generated from that same archive by `scripts/release-index.py`.

The first publisher primary fingerprint is:
`B835B40E7E1A5838390256751AB72B63BEB716C3`.
Publish the fingerprint on freo.live and in the verified 3andB repository/release
instructions. First-time users must establish trust in it through 3andB, not
merely accept any key arriving beside an archive. Private signing keys and their
passphrases must never be uploaded as release assets or committed to source.

The index schema is:

```json
{
  "latest_version": "VERSION",
  "schema_head": "ALEMBIC_REVISION",
  "platform": "ubuntu-24.04-x86_64",
  "download_url": "https://github.com/3andB/freo/releases/download/vVERSION/freo-vVERSION.tar.gz",
  "signature_url": "https://github.com/3andB/freo/releases/download/vVERSION/freo-vVERSION.tar.gz.asc",
  "sha256": "ACTUAL_SHA256",
  "supported_source_revisions": ["a71d25b609ef", "d02f9a41c830", "e83b9204c6af", "f39c8210b7de"]
}
```

These placeholders illustrate the contract; never publish them. Use the generated
file. Serve the same approved data from `GET https://api.freo.live/v1/releases/latest`
and use it for freo.live's download button. Preserve any required API contract
fields. Publish assets first, verify their actual public bytes and signatures,
then atomically update the stable index and invalidate its cache. A website
mirror must serve identical bytes and digest. Retain older releases and their
signatures for recovery. Do not silently substitute new bytes under an existing
version; fixes need a new version.

The central API may still return historical plan/channel/grace values. Update
its registration/pricing displays to the agreed three-station owner-wide terms.
Do not require periodic online entitlement refresh for the new offline license.
Freo 0.3 verifies that license locally and does not use cached expiry to revoke
its allowance. Reporting/account enrollment remains separate. Existing 0.2
clients have the historical behavior until upgraded, so do not claim this new
behavior for them or break the older API wire contract.

## Approval and publication procedure

1. Build from the exact clean version tag; CI produces a **candidate artifact**.
   It does not publish a GitHub Release or update the website/API.
2. Record unit/integration results and separate-VM fresh install, populated upgrade,
   reboot and restore acceptance. Attach defects and maintenance expectations.
3. Obtain explicit 3andB owner approval for that exact version/digest. Each public
   release needs approval. A repository push or successful build is not approval.
4. Publish the approved GitHub Release and identical assets. Verify the public
   downloads, signature, checksum and source/tag correspondence.
5. Update the website/API index to that release and verify the installation's
   version-check UI. Never put a prerelease candidate in the stable index.
6. Retain the acceptance record, approval, asset hashes and release notes. If a
   release is withdrawn, leave recovery assets available and stop advertising
   it; do not automatically downgrade customers or restore their databases.

Configure GitHub's `release` environment with required owner reviewers, restrict
release tags to maintainers, and prevent self-approval where available. The
workflow requires encrypted environment secrets `FREO_RELEASE_SIGNING_KEY`
(armored secret key) and `FREO_RELEASE_SIGNING_PASSPHRASE`, plus environment
variable `FREO_RELEASE_SIGNING_FINGERPRINT`. These repository settings are an
operator setup task; their presence has not been verified by the local build.
Keep manual owner sign-off even when the hosting plan cannot enforce reviewers.

## Invoice and license fulfillment (3andB operator only)

Keep a private record of purchaser/organization, invoice reference, payment and
issued license ID. After confirming the Stripe invoice is paid, use the trusted
source checkout's virtual environment:

```bash
venv/bin/python scripts/license-issuer.py issue --owner 'Purchaser or organization' --paid --private-key /PRIVATE/license-issuer.pem --passphrase-file /PRIVATE/license-passphrase --output /PRIVATE/purchaser.license.json
```

The output is private mode 0600. Send that JSON file to the purchaser through the
agreed delivery channel. They upload it in Admin → Software and license on each
owned installation. No online activation account is needed. Do not send the
private issuer key or passphrase. The license signature key is separate from the
release signing key. Back up both keys and their recovery material securely;
retain old public license keys in later releases so existing perpetual licenses
continue to work. Key rotation must add public keys, not invalidate paid customers.
A lost purchaser file can be resent from the private fulfillment record.

## Completion criteria for the website team

Verify desktop/mobile pages, working contact email, exact three-station/$99 copy,
canonical repository links, subtle creator credit, tested install instructions,
matching website/API version and digest, signature downloads and recovery links.
Provide the actual published URLs and verification results back to the owner.
Do not publish the candidate or contact customers until instructed by the owner.
