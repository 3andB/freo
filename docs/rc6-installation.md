# RC6 test kit: Ubuntu 24.04 x86_64

Version: **0.3.0-rc.6**. This is a signed private test candidate, not an accepted
stable release. The package's `release.json` records the exact source commit,
schema and file hashes. The outer kit's `validation.json` records completed and
pending checks. Neither a Git checkout nor an unsigned source-review archive
substitutes for this installer.

Use a new disposable Ubuntu 24.04 x86_64 VM. Keep production and the accepted RC5
VM unchanged. Permit SSH and inbound HTTP/HTTPS as needed. Backend ports remain
private. Outbound package repository and API access are needed. Allow room for
music, a complete encrypted backup and a verification restore.

## Get and verify the kit

The publisher supplies `freo-v0.3.0-rc.6-test-kit.tar` plus
`TEST-KIT-SHA256SUMS`. Transfer them to the VM using SCP/SFTP. Verify the outer
checksum, then extract it into an empty working directory:

```bash
sha256sum --check TEST-KIT-SHA256SUMS
tar -xf freo-v0.3.0-rc.6-test-kit.tar
cd freo-test-kit
```

Stop on any error. Install the public verification tools and verify the installer:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates gnupg
sha256sum --check SHA256SUMS
gpg --show-keys --with-fingerprint ./publisher.gpg
```

Confirm the **primary** publisher fingerprint against this independently supplied
trusted value before accepting the included public key:

`B835B40E7E1A5838390256751AB72B63BEB716C3`

Then verify the publisher signature and extract the application:

```bash
gpgv --keyring "$PWD/publisher.gpg" \
  freo-v0.3.0-rc.6.tar.gz.asc freo-v0.3.0-rc.6.tar.gz
mkdir freo-v0.3.0-rc.6
tar -xzf freo-v0.3.0-rc.6.tar.gz -C freo-v0.3.0-rc.6
cd freo-v0.3.0-rc.6
```

Do not continue if verification fails. Only the public key belongs in this kit;
private signing keys and passphrases are never transferred to the VM.

## Install once on a fresh VM

Choose **one** installation mode. For initial HTTP testing, replace the example
IP with the VM's reachable IP. Setting it explicitly avoids choosing an internal
address on VMs behind cloud NAT.

```bash
sudo env FREO_DOMAIN=YOUR_VM_PUBLIC_IP bash scripts/install.sh
```

For HTTPS instead, point a dedicated test domain at the VM first, replace both
example values, and run this command on a still-fresh VM:

```bash
sudo env FREO_DOMAIN=rc6.example.com FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=you@example.com bash scripts/install.sh
```

The installer uses bundled Python wheels with required hashes. Ubuntu/Xiph system
packages still require network access. Do not rerun the installer to switch modes
or upgrade; it intentionally refuses existing Freo state. If installation fails,
retain the output and report the failure before changing or reinstalling the VM.

## First login and validation

Open the printed `/admin/login` URL. Initial username: **admin**. Initial password:
**IAmOnTheAir**. Complete the mandatory setup with your email and a new password
of at least 16 characters. The initial password then stops working. No CLI account
creation is required. Freo Live registration and payment are optional.

```bash
cd /opt/freo
sudo venv/bin/python -c 'from app.version import VERSION; print(VERSION)'
sudo bash scripts/validate-install.sh
```

The version must be `0.3.0-rc.6`. There are no seeded demo stations or songs.
Create a station in Admin, import permitted test music, configure programming and
start broadcasting. Follow `rc6-acceptance.md` in the test kit.

Admin → Installation should show the same installed version and a successful
heartbeat. A null latest stable version and **Unknown** status are normal before
Freo Live discovers a stable GitHub Release. RC6 must not claim to be stable or
report the latest available version as its installed identity.

Reboot the VM, then repeat login, the validator and real playback. For HTTPS also
run `sudo certbot renew --dry-run`. Keep the VM and all test evidence until the
candidate is accepted or a separately numbered replacement is prepared.

## Existing installations and failures

Do not run this fresh installer on an existing installation. Test RC5 → RC6 on a
separate disposable installation created from the **unchanged signed RC5 package**.
Use the signed-bundle procedure in `recovery-and-upgrades.md`, including encrypted
backup, verified restore and preserved database/media/settings checks. Never use
the historical accepted RC5 VM for this exercise.

For a failed fresh install, retain the installer output. For runtime diagnostics:

```bash
sudo systemctl --failed --no-pager
sudo journalctl -u freo.service -u freo-central-api.service \
  -u freo-provision.service -u freo-ingest.service \
  --since '15 minutes ago' -n 120 --no-pager
```

Do not send `.env`, identity files, private keys, passwords or bearer credentials.
