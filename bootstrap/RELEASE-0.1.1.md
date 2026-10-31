# Bootstrap 0.1.1 — release asset compatibility

Bootstrap 0.1.0 served at https://freo.live/install requires a separate
PUBLISHER-FINGERPRINT.txt release asset and SHA256SUMS entry. The immutable
1.0.2 release does not publish either. Its pinned primary public key and detached
package signature already provide the publisher identity check.

0.1.1 removes the text-file dependency from discovery, checksums and verification.
It retains mandatory package/signature/key checksums, exact pinned primary-key
identity, isolated GPG keyring, signer/expiry/revocation checks, signed manifest
inventory, HTTPS restrictions, stable-release selection, fresh-server checks and
explicit installation confirmation. No application release assets are changed.

57 isolated tests passed, including real GPG wrong-key/tampering rejection and
loopback Nginx/TLS delivery. Public integration downloaded unchanged stable 1.0.2
(package SHA eabc4194ef903f8554d1fa73a756d3c946c688ff526bb4734de1bcc1e2c2557a),
verified the pinned publisher and all 614 manifest files, and extracted safely.
The installer was explicitly forbidden in this test. A fresh VM installation was
not repeated. See evidence/automated-results-0.1.1.json; historical evidence stays
unchanged.

Deployment: on the separately managed freo.live delivery host, retain current
bootstrap bytes, atomically publish this bootstrap/install.sh with root ownership
and mode 0644 to the configured /install alias target, and publish its matching
bootstrap/SHA256SUMS if that host exposes it. Keep the current plain-text/no-cache
Nginx delivery contract. Do not run the bootstrap on an existing application host.
Verify both public aliases return the exact new SHA256SUMS digest, run only
--bootstrap-version/--help, and repeat read-only public verification before
claiming the one-line installer is deployed. The existing signed-kit guide
remains supported. This source change alone does not update the remote endpoint.
