# Freo Bootstrap Installer 0.1.0

**Implementation candidate. Disposable fresh-VM acceptance is still required.**
Neither `https://freo.world/install` nor `/install.sh` has been deployed by this
project. Commands below use an illustrative isolated test hostname; substitute
the actual approved test delivery host. Do not run them on an existing server.

The bootstrap delivers an existing signed stable GitHub Release from
`3andB/freo`. It does not build Freo, upgrade an installation, change licensing,
or announce a release. Its independent version is 0.1.0. The application version
is selected at runtime and checked against signed package metadata.

## Requirements

- Fresh Ubuntu 24.04 x86_64/amd64 server with root/sudo access and sufficient
  disk space for Freo, downloaded/extracted packages, music, and recovery backups.
- Standard Ubuntu `python3` (3.12), CA certificates, and `curl` for the initial
  download. These are normally present on Ubuntu cloud images. A stripped image
  missing Python/CA certificates stops with instructions before changes: release
  discovery and the complete confirmation screen cannot safely precede their
  installation. Install those Ubuntu packages deliberately and try again.
- Working DNS, accurate system time, and outbound HTTPS for GitHub API/assets,
  Ubuntu/Xiph dependencies, and Freo Live. `api.ipify.org` is optional for public
  IPv4 discovery. No credentials or private metadata are sent to that service;
  it sees the outbound source address. Detection failure permits explicit input.
- Inbound HTTP and, for HTTPS, port 443. HTTPS needs a domain already pointing at
  the server, inbound port 80 for certificate validation, and a contact email.
  Remote browser microphone capture needs HTTPS and the documented WebRTC network
  configuration; HTTP installation alone does not enable remote microphone use.

An existing `/opt/freo` (even empty or a dangling symlink), Freo configuration,
data, service accounts/units, or PostgreSQL cluster configuration stops the
bootstrap. A general-purpose server with an existing database is not a fresh
bootstrap target. Use the supported
[upgrade/recovery procedure](https://github.com/3andB/freo/releases/download/v0.3.0/recovery-and-upgrades.md)
for an existing Freo installation. Never remove these guards to force a reinstall.

## One-command installation — test delivery host only

On the **disposable target VM**, replacing the illustrative test hostname:

```bash
(set -o pipefail; curl -fsS --proto '=https' --connect-timeout 15 --max-time 120 https://bootstrap-test.example.com/install | sudo bash)
```

The wrapper waits until its complete body has been received before executing.
The `pipefail` setting also makes an outer download failure fail the command.
No redirects are required for these exact delivery URLs.

The interactive confirmation reads `/dev/tty`, not the pipe. Before verification
tools or Freo are installed, the screen prominently shows:

```text
Freo Installer

Server: FREO-TEST
Public IP: 203.0.113.10
Installation address: http://203.0.113.10
OS: Ubuntu 24.04
Architecture: x86_64 / amd64
Bootstrap: 0.1.0
Installing Freo: 0.3.0

This will install Freo and configure services on this server.
Continue? [y/N]
```

The IP above is illustrative. Actual HTTP installation requires the server's
real public IPv4 address or DNS hostname. An automatic IPv4 default is offered
only when the HTTPS lookup matches a locally assigned global IPv4 address.
Otherwise the operator must supply an address; outbound NAT is not assumed to
identify an inbound-reachable installation. Detection never proves reachability.

An explicit HTTP address:

```bash
(set -o pipefail; curl -fsS --proto '=https' --connect-timeout 15 --max-time 120 https://bootstrap-test.example.com/install | sudo bash -s -- --domain radio.example.com)
```

Explicit HTTPS installation (substitute real domain/email):

```bash
(set -o pipefail; curl -fsS --proto '=https' --connect-timeout 15 --max-time 120 https://bootstrap-test.example.com/install | sudo bash -s -- --domain radio.example.com --https --email owner@example.com)
```

HTTP is supported, but login traffic is unencrypted. Prefer HTTPS for a public
server. Do not rerun the fresh installer to switch an installed server to HTTPS.

## Download, inspect, run

These commands assume Bash and a new directory. Obtain the expected bootstrap
SHA-256 from the reviewed handoff/evidence via an independently trusted channel.

```bash
mkdir freo-bootstrap-review
cd freo-bootstrap-review
curl -fsS --proto '=https' --connect-timeout 15 --max-time 120 \
  --output install.sh.part https://bootstrap-test.example.com/install &&
  mv install.sh.part install.sh
sha256sum install.sh
bash -n install.sh
less install.sh
```

**Stop if download, syntax, or expected-hash verification fails.** After review:

```bash
sudo bash install.sh --domain radio.example.com
```

Downloading a checksum beside the script alone is not independent proof of its
authenticity. The outer script relies on the approved HTTPS delivery host; its
pinned key authenticates the subsequent Freo package, not the script itself.

## Options

| Option | Behavior |
| --- | --- |
| `--domain HOST` | Explicit public IPv4 or DNS installation address |
| `--https` | HTTPS; requires explicit DNS domain and `--email` |
| `--email ADDRESS` | Certificate contact; only valid with `--https` |
| `--version 0.3.0` | That exact published stable release; leading `v` also accepted |
| `--yes` | Explicit noninteractive consent, including missing GnuPG tools; requires `--domain` |
| `--bootstrap-version` | Bootstrap version only |
| `--help` | Usage |

Noninteractive example after deliberate operator approval:

```bash
sudo bash install.sh --domain radio.example.com --https --email owner@example.com --yes
```

There are no alternate repository, mirror, key, unsigned, development, or
skip-verification options. `--yes` never bypasses preflight or verification.

## Release discovery and trust chain

1. Public GitHub API `/repos/3andB/freo/releases`, 100 entries/page, until the
   final page, with a hard 100-page limit. If the complete listing cannot be
   established, stop. Select highest numeric SemVer precedence, not list order
   or release date. Only `vVERSION` tags with a published stable Release qualify.
   Drafts, prerelease flags, SemVer prerelease suffixes (including RCs), and
   non-version tags are excluded. Equal highest precedence is ambiguous and
   stops; build metadata never makes a version newer.
2. `--version` uses the published-release-by-tag API and applies the same stable
   checks. A bare Git tag is insufficient. Missing assets on the selected release
   stop installation; the bootstrap never silently falls back to an older release.
3. Download only `freo-vVERSION.tar.gz`, its `.asc`, `publisher.gpg`,
   `PUBLISHER-FINGERPRINT.txt`, and `SHA256SUMS`. Construct and check exact GitHub
   release download URLs. Follow HTTPS redirects only to `github.com` or
   `release-assets.githubusercontent.com`; API redirects stay on `api.github.com`.
   Use OS TLS verification, no proxy/credential inheritance, bounded size/time,
   bounded retries, and exclusive `.part` files renamed only after completion.
4. Check API asset sizes/digests when present, then strict SHA-256 entries for
   every downloaded package/signature/key/fingerprint file. Checksum data is
   consistency evidence, not the publisher trust anchor.
5. Pin primary publisher fingerprint
   `B835B40E7E1A5838390256751AB72B63BEB716C3`. Reject unexpected/additional primary
   keys or private key material. Construct an isolated keyring containing only
   this identity. Verify the detached signature with `gpgv` and validate its
   machine-readable signer status, including expiration/revocation failures.
6. Only after signature verification, validate gzip completeness and safely
   extract regular files. Reject absolute/traversal/noncanonical/duplicate paths,
   links, devices, FIFOs, unexpected permission modes and oversized archives.
   Never use `tar -x` on unchecked member paths.
7. Check signed `release.json`: supported format/platform/Python, stable selected
   version, `development: false`, source commit shape, complete inventory, every
   file hash/size/mode, and static `app/version.py` identity. No package code is
   imported during verification.
8. Recheck fresh-install state. Invoke the verified `scripts/install.sh` with
   a clean environment and the existing HTTP/HTTPS inputs. `FREO_VERSION` is set
   from the verified version for the bundled provisioner's legacy release marker;
   the application's canonical version remains its unmodified signed source.

There is no runtime special case for 0.3.0. Its approved hash is asserted by the
separate public integration test and must be checked again in VM acceptance.
Future compatible stable versions are discovered without editing the script.
A new signing key or incompatible package platform/format requires a separately
reviewed bootstrap update. No Freo Live latest override or automatic upgrade exists.

## Failures and diagnostics

The root-owned workspace is `/var/tmp/freo-bootstrap-<random>` with mode 0700.
Downloads and diagnostics use mode 0600; extracted public code has safe 0644/0755
modes inside the private parent so the bundled copy step preserves service-readable
permissions. A root-owned lock prevents concurrent bootstrap runs.

On failure, stop and print the private workspace location. Retain diagnostics,
downloaded data and extraction evidence; incomplete download files are removed.
An extraction is not named `verified-release` until every check succeeds.
`verification.json` records verified source/version/hash and whether installation
started, failed/interrupted, or completed. `installer.log` records the bundled
installer's output without shell tracing or an inherited environment dump.

On success, remove temporary packages/keys/source and retain only the private
receipt and installer log. These are not automatically published. Review logs
before sharing: they may include operator contact details and installation output.
Never send `.env`, tokens, private keys, or passwords to support.

The bootstrap does not delete application state, roll back, repair, or retry the
Freo installer. A failed partial installation needs deliberate recovery or a new
disposable VM. It does not start a second reporter or manipulate credentials.

## Automated verification

Run outside the production checkout; no Freo dependencies or Flask configuration
are needed. Tests generate disposable signing keys, exercise harmless fixture
installers, and start an isolated **loopback-only** HTTPS Nginx with temporary
certificates/configuration. They never run the Freo installer or reload production
Nginx. Install test dependencies on a CI/test host, not by changing production.

```bash
bash -n bootstrap/install.sh
shellcheck bootstrap/install.sh
python3 -I -m unittest discover -s bootstrap/tests -v
```

The delivery test requires Nginx/OpenSSL; a skip is not an acceptance pass.
The public network integration test downloads the existing signed release into
a new directory and explicitly blocks installer execution:

```bash
python3 bootstrap/tests/verify_public_release.py --output /tmp/freo-public-verification-NEW
```

It checks real latest discovery, explicit stable discovery, all five downloaded
assets, real publisher/signature validation, all signed manifest entries, source
identity and the approved 0.3.0 SHA-256. No application package is rebuilt/signed.

See [VM acceptance and isolated HTTPS delivery](VM-ACCEPTANCE.md). Do not activate
freo.world's public installer until that acceptance and a separate deployment
approval are complete.
