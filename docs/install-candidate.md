# Freo 0.3.0-rc.2 installation candidate

This is a release candidate for a separate Ubuntu 24.04 x86_64 VM. Public release
requires the acceptance results below and explicit 3andB owner approval. Do not
install this candidate over the live Freo server. The installer refuses existing
state; upgrades use the separate recovery workflow.

## Obtain and verify

The publisher supplies these files together: `freo-v0.3.0-rc.2.tar.gz`, its
`.asc` detached signature, `SHA256SUMS`, and `publisher.gpg`. Until approved,
transfer these candidate files privately from the build server using SCP/SFTP.
They are not yet a published GitHub Release. Never transfer publisher private
keys or the publisher directory to a customer VM.

Expected publisher fingerprint (confirm through 3andB's independently trusted
channel before first use):

`B835B40E7E1A5838390256751AB72B63BEB716C3`

On the fresh VM, put the four files in an otherwise empty directory, enter it,
and run:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates gnupg
# Check the primary fingerprint against the trusted value above.
gpg --show-keys --with-fingerprint ./publisher.gpg
sha256sum --check SHA256SUMS
gpgv --keyring "$PWD/publisher.gpg" freo-v0.3.0-rc.2.tar.gz.asc freo-v0.3.0-rc.2.tar.gz
mkdir freo-v0.3.0-rc.2
tar -xzf freo-v0.3.0-rc.2.tar.gz -C freo-v0.3.0-rc.2
cd freo-v0.3.0-rc.2
```

Stop if any check fails. The signature authenticates the complete archive. The
checksum alone does not establish publisher identity. Dependencies are bundled
as wheels and installed with required hashes; system packages still need access
to Ubuntu and the official Xiph package repository.

## Fresh installation

Start with a dedicated clean VM. Allow SSH and HTTP/HTTPS in its firewall/security
group; keep PostgreSQL, Gunicorn and Icecast backend ports private. Ensure enough
disk capacity for the music library, staged release, encrypted backup and a full
verification restore. Capacity depends on your library; no performance or station
capacity guarantee is implied by the unlimited license.

For the first IP-only HTTP acceptance run:

```bash
sudo env FREO_VERSION=0.3.0-rc.2 bash scripts/install.sh
cd /opt/freo
sudo env FREO_ENV_FILE=/opt/freo/.env venv/bin/flask --app wsgi:app admin set-password --email YOUR_EMAIL
sudo bash scripts/validate-install.sh
```

Replace `YOUR_EMAIL`. The command prompts twice for a password of at least 16
characters without echoing it. No default account is installed. The first admin
receives installation management permission. Open `http://VM_IP/admin` and sign
in. Use an SSH tunnel for initial HTTP administration if the network is not
trusted; complete HTTPS before normal public administration.

For a fresh domain installation instead, point DNS at the VM first, then use:

```bash
sudo env FREO_VERSION=0.3.0-rc.2 FREO_DOMAIN=radio.example.com FREO_ENABLE_HTTPS=1 FREO_CERTBOT_EMAIL=operator@example.com bash scripts/install.sh
```

Replace the example domain and email. This obtains a Let’s Encrypt certificate,
redirects HTTP to HTTPS, saves the HTTPS public URL and enables `certbot.timer`.
After installation run `sudo certbot renew --dry-run` on the test VM to verify
renewal with its actual DNS and network configuration.

Replace the example values before use. Do not run this second install command on
an already installed VM. To add HTTPS after the IP-only run, configure the
intended Nginx server name, obtain its certificate with Certbot, and update the
saved public URL/domain settings using `flask settings set` with the current
revision, as described in [recovery and upgrades](recovery-and-upgrades.md).

The installer creates no demo stations or music. Create a station in Admin,
upload audio you may legally broadcast, configure its programming, and start it.
Live microphone gateways need the separate [live microphone setup](live-mic.md)
where applicable; installing dependencies does not enable a gateway automatically.

Registration is optional. Freo automatically reports installation identity,
version, machine facts, channel metadata and aggregate totals to api.freo.live.
It does not send listener identities/IPs or music metadata. Public directory
listing requires a separate opt-in. See [reporting details](central-api-integration-plan.md).

## License

Free use covers three stations total per owner across installations, including
commercial use. Above three, email info@3andB.com. 3andB emails a Stripe invoice;
after payment, it sends an owner-wide license file. US$99 is a one-time payment
for unlimited stations across all installations the purchaser owns, including
all future updates. Registration is not required. Counting across installations
is honor-based. The same license file can be activated on each owned installation.

In Admin → Software and license, upload the supplied JSON file. Verification
works offline, has no periodic renewal and does not depend on the central API's
cached plan. The activated license is stored in PostgreSQL and included in database
backup/restore. Keep the original file privately as well. Do not commit it to Git.

## Existing installations and web upgrades

Do not rerun the installer. Follow [recovery and upgrades](recovery-and-upgrades.md)
with a signed release, a private recovery key, a full backup, and an isolated
PostgreSQL verification connection. That process verifies an actual restore
before migration and preserves existing rows and media hashes.

The 0.3 migration grants no new installation privileges to existing accounts.
After a CLI upgrade, the root operator explicitly grants the chosen owner admin:

```bash
cd /opt/freo/current
sudo env FREO_ENV_FILE=/etc/freo/freo.env venv/bin/flask --app wsgi:app admin installation-role YOUR_EMAIL --grant
```

The first upgrade from 0.2 uses the CLI. On legacy systems, install the new runner
once after a successful upgrade (fresh 0.3 installations already have it):

```bash
cd /opt/freo/current
sudo venv/bin/python - <<'PY'
from pathlib import Path
from freo_ops.upgrade import rewrite_unit
for name in ('freo-updater.service', 'freo-updater.timer'):
    target = Path('/etc/systemd/system') / name
    if target.exists():
        raise SystemExit('Existing updater unit requires operator review: ' + str(target))
    target.write_text(rewrite_unit((Path('deploy/systemd') / name).read_text()))
    target.chmod(0o644)
PY
sudo systemctl daemon-reload
sudo systemctl enable --now freo-updater.timer
```

For later browser-approved upgrades, root first prepares a specific verified
artifact. Substitute absolute paths, a new backup filename and a new restore
directory. The verification environment contains a maintenance connection with
CREATEDB permission, never the current application database as a restore target.
Use the initial `/opt/freo/.env` before managed adoption and
`/etc/freo/freo.env` afterward. Run from the installed/current code directory:

```bash
sudo venv/bin/python -m freo_ops.web_updates --env-file /etc/freo/freo.env prepare /DOWNLOADS/freo-vNEXT.tar.gz --signature /DOWNLOADS/freo-vNEXT.tar.gz.asc --keyring /PRIVATE/publisher.gpg --backup /BACKUP_VOLUME/pre-NEXT.gpg --passphrase-file /PRIVATE/recovery.key --verification-env-file /PRIVATE/verification.env --verification-directory /RESTORE_VOLUME/pre-NEXT
```

This only prepares the request; it does not stop broadcasts. An installation
administrator then opens Software and license and explicitly approves the
maintenance interruption. Station administrators cannot queue upgrades. The root
timer accepts only the prepared identifier; the browser cannot provide commands,
URLs or filesystem paths. It runs the same backup, restore and preservation checks
as the CLI. Leave the recovery key available privately until the job finishes.

An interrupted/running request is never retried automatically. The operator must
inspect `python -m freo_ops upgrade-status`, recover deliberately using the
runbook, and preserve the failed state. After recovery, mark the specific stale
`system_upgrades` row failed through a reviewed database transaction before
preparing a fresh request. Do not restore a backup over a database with new writes.

## Acceptance record required before public launch

Record the candidate digest, VM image, package versions and results. On this
separate VM verify:

1. Installation finishes, `/health` and `/ready` succeed, and admin login works.
2. Create stations, upload legal test audio, save settings/programming, and hear
   real decoded audio through the public stream. Record hashes and saved values.
3. Reboot; verify the same accounts, settings, audio and intended running stations.
4. Installer rerun refuses before changing existing state; record unchanged hashes.
5. Exercise signed upgrade from the supported prior release with populated data.
   Verify saved rows, original file hashes, admin permissions and any activated
   license survive. Check CLI and prepared browser approval on suitable baselines.
6. Verify a bad signature is rejected, an interrupted migration blocks automatic
   restart, and recovery into new locations works on a replacement VM. Record
   interruption duration and any manual steps.
7. Run the expanded [clean-install checklist](clean-install-test.md), including
   isolation, HTTPS and feature checks used by your installation.

A passing unit/integration suite is not a substitute for these real systemd,
network, reboot and radio tests. Public publication remains blocked until this
record and explicit owner approval exist.
