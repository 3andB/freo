# Freo 0.3.2

**Fresh installation and reboot recovery tested and passed on Ubuntu 24.04
x86_64.** This release publishes the exact signed stable kit accepted on a fresh
VM: automatic dependency setup, PostgreSQL migrations, music processing,
playlist scheduling and live playback, followed by automatic broadcasting
recovery after a full reboot. Installer and validators exited 0; no systemd
units failed before or after reboot.

[Install Freo 0.3.2](https://github.com/3andB/freo/releases/download/v0.3.2/INSTALLATION.md)
· [Download the complete installation kit](https://github.com/3andB/freo/releases/download/v0.3.2/freo-v0.3.2-install-kit.tar)
· [Upgrade and recovery](https://github.com/3andB/freo/releases/download/v0.3.2/recovery-and-upgrades.md)
· [Acceptance details](https://github.com/3andB/freo/releases/download/v0.3.2/ACCEPTANCE.md)

Changes since 0.3.0:

- Automatically install both PostgreSQL drivers. Retain pinned psycopg and
  psycopg-binary 3.3.6, psycopg2-binary 2.9.13, SQLAlchemy 2.0.54, and packaging 26.3.
- Validate the actual Freo Nginx vhost locally, preserving HTTP Host, HTTPS SNI,
  certificate verification, cookies and CSRF. Report local application validation
  separately from public/hairpin reachability and print the exact admin URL.
- Preserve Back/Forward and link navigation while page responses are loading.
- Correct Cue completion and AUTO successor handling around playback transitions.
- Stop timer-started workers before upgrade backup; align model event-index
  metadata with the existing migration without rewriting historical migrations.
- Keep development tests, fixtures, CI and contributor files out of the customer
  archive and installed application; retain runtime assets and operator docs.

The regression inventory accounts for **1,273 passed, three optional skips and
no unresolved failures**. Exact-archive offline dependency, PostgreSQL, web/TLS,
upgrade and matched-recovery checks passed. See acceptance details for retained
run provenance, the observed audio load sensitivity and the precise VM scope.
Public certificate issuance/renewal requires verification on your own HTTPS
installation; the final owner VM used HTTP/public IP.

Source tag `v0.3.2` identifies **83200e6508654bea13f404e9d5699a8ad3eae19d**.
Subsequent repository documentation records completed acceptance; it does not
change the signed package. No archive was rebuilt after the owner's test.

Outer installation kit SHA-256:
`2488f8784243fd5bfed4116ea4aff6c0ee6b15f619361379650b7405a269b91a`

Signed inner archive SHA-256:
`7bfc8a573a59dfa210478da9c2b80fccbb0ebcde297a85d4ae56856d96709c4f`

Publisher fingerprint: `B835B40E7E1A5838390256751AB72B63BEB716C3`.

The kit retains its `freo-test-kit/` directory and preparation-time documents to
preserve the tested bytes. `ACCEPTANCE.md` and `INSTALLATION.md` provide the
current release status. Use the named installation kit, not GitHub's generated
source archives. Existing users must follow the signed upgrade/recovery procedure;
do not rerun the fresh installer.

Freo is source-available. Three stations total per owner are free, including
commercial use; US$99 once covers unlimited stations across the owner's
installations and future updates. Registration is optional.
