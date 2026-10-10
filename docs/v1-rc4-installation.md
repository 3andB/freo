# Freo World V1 RC4 test installation

`1.0.0-rc.4` keeps the existing installer, restricted SSH contract and read-only
Studio release API. It fixes microphone safety-lease starvation when a worker
processes several stations: prepared sessions are synchronized between station
work, with the existing authorization and six-second engine lease unchanged.
The repository policy selects matching Xiph `libigloo-dev` headers alongside
the existing `libigloo0` runtime, while keeping unrelated Xiph packages blocked.
This prevents Ubuntu 0.9.2 headers from breaking the required native build.
The updater applies the same fingerprint-checked repository policy before
resolving native build dependencies, after verifying its recovery point.
The signed manifest also admits the existing V1 schema as an upgrade source,
so RC1/RC2 hosts can apply this correction through the same verified updater.
It is a private candidate, not a stable V1 release.

Use the fresh installer only on an empty Ubuntu 24.04 x86_64 server. An existing
installation requires the signed, encrypted-backup and verified-restore upgrade
workflow in [recovery and upgrades](recovery-and-upgrades.md), with explicit
candidate authorization and a rehearsed maintenance window. Never run the fresh
installer over existing customer data. The [RC1 restricted SSH contract](v1-rc1-installation.md)
continues to define hosting configuration, service management and verification.

Obtain the RC4 kit, detached signature, and publisher public key through a
trusted release handoff. Confirm the independently pinned publisher fingerprint
`B835B40E7E1A5838390256751AB72B63BEB716C3` before trusting the key file.
From a root-owned staging directory, verify the outer kit before extraction:

```sh
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.0-rc.4-install-kit.tar.asc freo-v1.0.0-rc.4-install-kit.tar
sha256sum --check freo-v1.0.0-rc.4-install-kit.sha256
mkdir rc4-kit
tar -xf freo-v1.0.0-rc.4-install-kit.tar -C rc4-kit
cd rc4-kit
sha256sum --check SHA256SUMS
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.0-rc.4.tar.gz.asc freo-v1.0.0-rc.4.tar.gz
mkdir source
tar -xzf freo-v1.0.0-rc.4.tar.gz -C source
```

Stop on any verification failure. Never run an unverified archive's scripts.
Use the RC1 command contract with the RC4 source path. On a test server with an
assigned domain and working A record, enable HTTPS and use a real operator
email for certificate issuance. For IP-only acceptance, omit HTTPS/email;
the Studio release API remains inaccessible until HTTPS is configured.

```sh
cd source
env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
  FREO_DOMAIN=radio.example.com FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=operator@example.com FREO_LIVE_MIC=1 \
  bash scripts/install.sh
freo-admin status
freo-admin hosting configure --plan starter
bash /opt/freo/scripts/validate-install.sh
freo-admin hosting verify
freo-admin health
```

The Studio release API needs the root-approved file inventory and hash-only
key file described in its own contract. The ordinary installer does not create
or publish a release inventory or issue a Studio key. Provision those files
from the independently verified handoff, then check all four HTTPS endpoints
with the Bearer key. A valid API response does not replace SSH installation,
hosted-mode enforcement, or the disposable station/reboot acceptance checks.
