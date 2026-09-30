# Install Freo 0.3.2

**Fresh installation and reboot recovery: tested and passed on Ubuntu 24.04
x86_64.** The published installation kit is the exact signed kit accepted on a
fresh VM, without rebuilding. Freo installed its own dependencies, processed
music uploads, played a playlist through Simple scheduling, and automatically
returned to broadcasting after reboot. Installer and before/after-reboot
validators exited 0; no systemd units failed.

Use a fresh Ubuntu 24.04 x86_64 server with SSH access and inbound HTTP port 80
(or ports 80/443 for HTTPS). Allow disk space for music and protected backups.
Python dependencies are bundled and hash-locked. Network access is required for
Ubuntu/Xiph system packages. No manual Python/PostgreSQL setup is needed.

Existing installations: use the [upgrade and recovery guide](https://github.com/3andB/freo/releases/download/v0.3.2/recovery-and-upgrades.md).
Do not run the fresh installer over an existing or partially installed station.

## Download and verify

Run these commands on the new server. Use `sudo` as shown, or omit it when
already root. Install download/verification tools first if needed:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
mkdir -p "$HOME/freo-install-0.3.2"
cd "$HOME/freo-install-0.3.2"
curl --fail --location --proto '=https' --proto-redir '=https' \
  --output freo-v0.3.2-install-kit.tar \
  https://github.com/3andB/freo/releases/download/v0.3.2/freo-v0.3.2-install-kit.tar
printf '%s  %s\n' \
  '2488f8784243fd5bfed4116ea4aff6c0ee6b15f619361379650b7405a269b91a' \
  'freo-v0.3.2-install-kit.tar' | sha256sum --check
```

Stop if any command or verification fails. After the outer checksum passes:

```bash
tar -xf freo-v0.3.2-install-kit.tar
cd freo-test-kit
sha256sum --check SHA256SUMS
gpg --show-keys --with-fingerprint publisher.gpg
```

Confirm the publisher fingerprint against this independently published value:

**B835 B40E 7E1A 5838 3902 5675 1AB7 2B63 BEB7 16C3**

```bash
gpgv --keyring "$PWD/publisher.gpg" freo-v0.3.2.tar.gz.asc freo-v0.3.2.tar.gz
mkdir freo-v0.3.2
tar -xzf freo-v0.3.2.tar.gz -C freo-v0.3.2
cd freo-v0.3.2
```

Expect a good signature from `3andB Freo Releases <info@3andB.com>`.
The directory name `freo-test-kit` and preparation-time notices inside the kit
are retained to preserve its tested bytes. The public release notes and
`ACCEPTANCE.md` record the subsequent completed acceptance and publication
approval. GitHub's automatically generated source ZIP/tar downloads do not
contain the bundled installation dependencies; use the named installation kit.

## Install once

For HTTP, replace `YOUR_SERVER_PUBLIC_IP` with the server's public IPv4 address
(or your configured hostname):

```bash
sudo env FREO_DOMAIN=YOUR_SERVER_PUBLIC_IP bash scripts/install.sh
```

This explicitly selects the public URL and Nginx virtual host. Leaving it unset
uses the first local address, which may be private on a server with multiple
interfaces.

For HTTPS, point a real hostname at the VM, allow ports 80/443, and run this
**instead**, replacing the hostname and email:

```bash
sudo env FREO_DOMAIN=radio.example.com FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=you@example.com bash scripts/install.sh
```

HTTPS requires public DNS and successful certificate issuance. Remote browser
microphone access requires HTTPS. Automated TLS/Host/SNI/certificate checks
passed; the final owner VM acceptance used HTTP/public IP. Verify public
certificate issuance and `sudo certbot renew --dry-run` on your HTTPS server.

The installer configures PostgreSQL, migrations, Nginx, Gunicorn and radio
services. It reports:

- **LOCAL APPLICATION VALIDATION**: Freo, Nginx and the admin login path on the VM.
- **EXTERNAL ACCESS VALIDATION**: public reachability from that VM, reported
  separately so blocked hairpin routing cannot falsely fail a working local app.

A successful install prints the exact address to open, for example:
`http://YOUR_SERVER_PUBLIC_IP/admin/login`. Check it from another device.
If installation exits nonzero, preserve its output and investigate before rerunning.

## First broadcast

Sign in as **admin** with **IAmOnTheAir**. Immediately complete mandatory setup
with your email and a new password, then accept the license agreement. Freo
starts without demo stations or music. Create your station, upload audio you
are permitted to broadcast, wait for processing, create a playlist and assign
it in Simple scheduling. Turn broadcasting on and open the public player.
The primary administrator manages upgrades and licenses. Registration is optional.

```bash
cd /opt/freo
venv/bin/python -c 'from app.version import VERSION; print(VERSION)'
sudo bash scripts/validate-install.sh
systemctl --failed --no-pager
```

Expect version `0.3.2`, successful local/service/database checks and no failed
units. Leave broadcast on, reboot when convenient, and confirm automatic
playback recovery and retained station/media/settings. Run the validator again.

## Reporting, licensing and recovery

Freo automatically reports installation identity, version, machine facts,
station metadata and hourly aggregate listener/library totals to api.freo.live.
It does not send listener identities/IPs or music metadata. Directory listing
requires a separate opt-in. Registration is optional.

Freo is source-available. Up to three stations total per owner are free,
including commercial use; US$99 once covers unlimited stations across that
owner's installations and future updates. See the bundled LICENSE.

Arrange protected off-server backups and verify a matched recovery point using
the [recovery guide](https://github.com/3andB/freo/releases/download/v0.3.2/recovery-and-upgrades.md).
Use the supported signed updater for existing installations. Never try to
reverse the security migration as a recovery shortcut.
