# Freo World V1 RC1 installation and SSH contract

RC1 is `1.0.0-rc.1`, for a dedicated Ubuntu 24.04 x86_64 server. It is a
candidate for testing, not a stable release. Never install it over production
0.3.2. There is one distribution for self-hosted and Studio-hosted operation.

Freo World owns installation, supported local commands, validation and local
security enforcement. Freo Studio owns infrastructure provisioning, SSH identity,
authentication, command dispatch and orchestration. Studio is a separate project;
its dispatcher is neither supplied nor assumed compatible. No management API,
remote execution service or additional daemon is installed.

## Verify before executing

The kit contains `freo-v1.0.0-rc.1.tar.gz`, its detached `.asc` signature,
`SHA256SUMS`, and `publisher.gpg`. Confirm the publisher fingerprint through an
independently trusted channel:

`B835B40E7E1A5838390256751AB72B63BEB716C3`

Use a root-owned staging directory inaccessible for writing by customers. The
following commands are local privileged bootstrap operations, not permission to
expose arbitrary commands through Studio's SSH dispatcher:

```sh
apt-get update
apt-get install -y ca-certificates gnupg
cd /root/freo-rc1-kit
gpg --show-keys --with-fingerprint publisher.gpg
sha256sum --check SHA256SUMS
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.0-rc.1.tar.gz.asc freo-v1.0.0-rc.1.tar.gz
mkdir source
tar -xzf freo-v1.0.0-rc.1.tar.gz -C source
```

Stop on any failure or fingerprint mismatch. A checksum alone does not establish
publisher identity. Never use an unverified archive's own script to authenticate
that archive. Private keys and signing passphrases are never distributed.

The package contains hash-locked Python wheels, including optional microphone
dependencies. Ubuntu/Xiph packages and certificate issuance still need network
access. Initial hosted enablement can build the existing pinned, patched Icecast
engine and install its build prerequisites.

## Minimal command sequence

Run as root, using a clean environment and the verified fixed source location:

```sh
cd /root/freo-rc1-kit/source
env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
  FREO_DOMAIN=radio.example.com FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=operator@example.com FREO_LIVE_MIC=1 \
  bash scripts/install.sh
freo-admin status
# Only for Studio-hosted installations:
freo-admin hosting configure --plan starter
bash /opt/freo/scripts/validate-install.sh
freo-admin hosting verify
freo-admin health
freo-admin services status
```

Replace the example domain/email with validated deployment values. DNS must
already resolve to this server. For an IP-only disposable test, set FREO_DOMAIN
to its IP and omit HTTPS/email. Use HTTPS for customer credentials and public use.
The optional microphone flag defaults to `0`; set it to `1` when required.
Self-hosted mode defaults to `{"hosted":false}` and requires no hosting command.
Do not admit customers until hosted configuration and all required checks pass.

The bootstrap admin is `admin` / `IAmOnTheAir`. First login requires a private
replacement password. Verification checks this flow without claiming the account.
No demo station or music is seeded by ordinary installation. The separate,
explicit disposable acceptance command below claims setup and creates stations.

The installer prints human-readable progress and returns 0 only after local
validation passes; nonzero is failure. External reachability is separately
reported: verify DNS, HTTPS and firewall access from Studio's network before
handoff. Do not infer external success from local validation.

Installation is not an upgrade or an automatic repair command. A second invocation
refuses existing Freo state. After interruption, retain logs, inspect the state,
and rebuild a disposable server or use reviewed recovery; never delete customer
state automatically. Dependency installation has no total fixed deadline. Studio
should allow at least 30 minutes for installation/initial hosting configuration;
a timeout is an unknown outcome to inspect, not permission to replay blindly.
Serialize mutating operations per server. Read status/health after reconnecting.

## Restricted SSH surface

Studio's forced-command dispatcher must translate validated operation arguments
to fixed executable/argument arrays, with no shell interpolation, interactive
shell, forwarding, caller-selected paths, URLs, systemd units or environment.
Only privileged infrastructure administrators may stage verified code or invoke
bootstrap. Customer accounts must not have root, sudo or write access to the
code, parent directories, policy, units, Nginx or Icecast configuration.

| Operation | Freo command | Result / retry |
| --- | --- | --- |
| Install | Verified `scripts/install.sh`, fixed staging path and allowlisted environment above | Logs; 0 success; refuses existing state |
| Validate installation | Installed `scripts/validate-install.sh` | Repeatable; nonzero on local failure |
| Inspect | `freo-admin status`, `health`, `services status` | JSON; safe to repeat |
| Assign capacity | `freo-admin hosting configure --plan starter` or `pro` | Verify actual returned state |
| Custom capacity | `freo-admin hosting configure --plan custom --stations N --listeners N --bitrate N --storage-gb N` | All four positive limits required; bitrate >=64; listener maximum 32640 |
| Verify policy | `freo-admin hosting verify`, `storage` | Repeatable JSON observations |
| Service state | `freo-admin hosting past-due`, `suspend --reason TEXT`, `maintenance`, `activate` | Preserves policy; inspect after interruption |
| Restart | `freo-admin services restart --service NAME` | Approved names only; verifies resulting health |
| Reconcile | `freo-admin services recover` | Honors inhibition and pending recovery; no implicit database rollback |

Approved service names: `application`, `icecast`, `playout`, `microphone`, `ingest`,
`automation`, `production`, `statistics`, `scheduled-workers`. Suspension reason
is plain text, at most 160 characters. Do not expose arbitrary `systemctl`.

`freo-admin` responses use `schema_version:1`, `success`, and operation-specific
fields. Require both exit 0 and `success:true`. Exit 2 means invalid arguments,
3 unauthorized, 4 capacity/state conflict, 5 invalid configuration, 6 operational
or verification failure. Lifecycle commands additionally use the documented
errors in [the existing command contract](freo-studio-hosting-integration.md).
`health: intentionally_suspended` is successful only when policy requires stopped
audio and verification confirms it. During suspension, sign-in page/cookies are
checked; setup and operational API routes remain intentionally unavailable. Full listener capacity and draining sessions
are represented explicitly; neither authorizes bypassing limits.

After signed upgrades, use `/opt/freo/current/scripts/validate-install.sh` when
`/opt/freo/current` exists. The installed `freo-admin` launcher resolves the active
release itself. Backup/restore/upgrade commands retain their existing contract;
bootstrap authorization does not authorize a destructive restore.

## Disposable acceptance and reboot

On an explicitly disposable, newly installed server only:

```sh
cd /opt/freo
venv/bin/python scripts/accept-install.py fresh --confirm-hostname Freo-v1-Test-1
venv/bin/python scripts/accept-install.py hosted --confirm-hostname Freo-v1-Test-1
```

The runner uses existing login, station and hosting operations. It creates two
test stations, replaces the bootstrap password with a private generated password,
and records JSON evidence plus private test credentials under
`/var/lib/freo-admin/rc1-acceptance`. It refuses a nonempty fresh-install fixture.
It never runs automatically on a customer's installation. Keep the test stations
for reboot checks, then rebuild the disposable server before customer handoff.

Reboot is owned by infrastructure orchestration, outside the restricted Freo
service surface. Record the boot ID and installation ID before reboot. After
reconnection run `validate-install.sh`, `freo-admin health`, and `hosting verify`;
require a changed boot ID, unchanged installation ID, and working active streams.
Suspend with `freo-admin hosting suspend --reason rc1-reboot-test`, repeat the
reboot checks, and require stopped streams. Only explicit `hosting activate`
should restore audio. Check microphone service state when enabled.

Passing unit tests or checks on a reused OS is not proof of pristine-OS acceptance.
The RC1 test report records exactly which environment and artifact were exercised.
