# Freo World V1 RC2 test installation

`1.0.0-rc.2` adds the read-only [Studio release API](studio-release-api.md) to
the existing V1 installer and hosting command surface. It is a private test
candidate, not a stable release. Install only on a dedicated Ubuntu 24.04
x86_64 VPS, never over production 0.3.2. The [RC1 installation and restricted
SSH contract](v1-rc1-installation.md) remains the command contract for hosting
configuration, service management, validation, and reboot checks.

Obtain the RC2 kit, detached signature, and publisher public key through a
trusted release handoff. Confirm the independently pinned publisher fingerprint
`B835B40E7E1A5838390256751AB72B63BEB716C3` before trusting the key file.
From a root-owned staging directory, verify the outer kit before extraction:

```sh
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.0-rc.2-install-kit.tar.asc freo-v1.0.0-rc.2-install-kit.tar
sha256sum --check freo-v1.0.0-rc.2-install-kit.sha256
mkdir rc2-kit
tar -xf freo-v1.0.0-rc.2-install-kit.tar -C rc2-kit
cd rc2-kit
sha256sum --check SHA256SUMS
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.0-rc.2.tar.gz.asc freo-v1.0.0-rc.2.tar.gz
mkdir source
tar -xzf freo-v1.0.0-rc.2.tar.gz -C source
```

Stop on any verification failure. Never run an unverified archive's scripts.
Use the RC1 command contract with the RC2 source path. On a test server with an
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
