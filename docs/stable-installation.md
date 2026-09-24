# Freo 0.3.0 installation

Status: **installer staged for publication**. A signed package, local tag or
merge to main does not announce a public release. Publication requires a separate
approved stable GitHub Release in `3andB/freo`. Never replace the RC9 artifact
with this package: 0.3.0 has its own version, source commit, signature and hashes.

## Requirements

Use a **fresh Ubuntu 24.04 x86_64 VM**, with SSH and inbound HTTP/HTTPS as
needed. Allow space for music, an encrypted backup and a restore verification.
The package bundles hash-locked Python wheels; Ubuntu/Xiph system packages
require network access. No Freo Live account or payment is required.

Existing installations must use the [verified updater](recovery-and-upgrades.md).
Do not run the fresh installer over an existing installation.

## Obtain and verify

Until publication, obtain `freo-v0.3.0-install-kit.tar` and `KIT-SHA256SUMS`
from the publisher via SCP/SFTP. Do not assume a public download exists.

```bash
sha256sum --check KIT-SHA256SUMS
tar -xf freo-v0.3.0-install-kit.tar
cd freo-install-kit
sudo apt-get update
sudo apt-get install -y ca-certificates gnupg
sha256sum --check SHA256SUMS
gpg --show-keys --with-fingerprint ./publisher.gpg
```

Confirm the primary signing fingerprint against this independently supplied value:

`B835B40E7E1A5838390256751AB72B63BEB716C3`

```bash
gpgv --keyring "$PWD/publisher.gpg" \
  freo-v0.3.0.tar.gz.asc freo-v0.3.0.tar.gz
mkdir freo-v0.3.0
tar -xzf freo-v0.3.0.tar.gz -C freo-v0.3.0
cd freo-v0.3.0
```

Stop if any verification fails. The kit contains only the public verification
key; never transfer private signing material to an installation.

## Install once

Choose one mode. For HTTP, replace the example with your public IP or domain:

```bash
sudo env FREO_DOMAIN=YOUR_PUBLIC_IP_OR_DOMAIN bash scripts/install.sh
```

For HTTPS, first point your domain at the VM, then instead run:

```bash
sudo env FREO_DOMAIN=radio.example.com FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=you@example.com bash scripts/install.sh
```

Use real domain/email values. HTTPS is required for microphone capture from
remote browsers. Do not rerun the installer to change modes or upgrade.

## First use

Open the printed `/admin/login` URL. Sign in as **admin** with the initial
password **IAmOnTheAir**. Mandatory setup requires your email and a new password
of at least 16 characters. The initial password then stops working. The primary
admin receives access to `/admin/software` automatically.

Create a station in Admin, import music you can broadcast, configure programming
and start playback. No demo stations or music are seeded.

```bash
cd /opt/freo
sudo venv/bin/python -c 'from app.version import VERSION; print(VERSION)'
sudo bash scripts/validate-install.sh
```

The installed version must be `0.3.0`, also shown in Admin → Installation and
reported through the existing heartbeat. Latest stable may remain Unknown
until Freo Live discovers a published stable GitHub Release. Preparing this
package does not update that service's latest version.

Verify first login, Software access, music import, programming, external playback
and restart persistence. For HTTPS, also verify `sudo certbot renew --dry-run`
and microphone return to the previous feed. The kit's `validation.json` separates
completed automated checks from operator/VM acceptance. A stable version number
alone does not prove acceptance.

## Recovery and support

Retain installer output on failure. Do not delete state and rerun blindly. Use
[recovery and upgrades](recovery-and-upgrades.md) for backups and signed upgrades.
Upgrades from older candidates require a fresh admin sign-in because the logout
fix revokes sessions at the server. Accounts and station data remain intact.

Diagnostics:

```bash
sudo systemctl --failed --no-pager
sudo journalctl -u freo.service -u freo-central-api.service \
  -u freo-provision.service -u freo-ingest.service \
  --since '15 minutes ago' -n 120 --no-pager
```

Never share `.env`, installation identity files, passwords or bearer tokens.
