# Bootstrap disposable-VM acceptance

Status: **pending operator execution**. Passing automated tests is insufficient.
Keep the existing 0.3.0 release and freo.world untouched throughout this exercise.

## 1. Prepare isolated HTTPS delivery

Use a separate staging host/domain with a publicly trusted certificate. Do not
use production freo.world or add installer routes to the Freo application.
The serving host must be separate from the fresh target being accepted.

1. Choose a real test hostname (examples here use `bootstrap-test.example.com`).
   Point its DNS to the staging host and provision its normal trusted HTTPS
   certificate through the staging host's approved process. No `curl -k` and no
   untrusted certificate exception for the customer-experience test.
2. Transfer **the exact reviewed `bootstrap/install.sh`** to that host. Verify its
   SHA-256 against this handoff before and after copying. Do not edit/substitute
   it while testing. Both versions must remain visible in the confirmation.
3. On that staging host only, install the file as root-owned
   `/srv/freo-bootstrap/install.sh` mode 0644, with root-owned directory mode 0755.
4. Include `nginx/bootstrap-locations.conf` inside the test hostname's HTTPS
   server block. Both exact endpoints serve the same file, plain text, without
   proxying or template evaluation. Keep ordinary HTTP-to-HTTPS redirect rules
   as appropriate for the test host; the tested bootstrap URL itself is HTTPS.
5. Run `nginx -t` and reload **that staging Nginx only**. This repository does not
   contain or run an automatic production deployment step.
6. From an independent client, request both HTTPS URLs, verify status 200,
   `Content-Type: text/plain; charset=utf-8`, `X-Content-Type-Options: nosniff`,
   and exact bootstrap SHA-256. Run `bash -n` on downloaded bytes without running
   the bootstrap on the delivery server. Verify `/install/anything` does not
   return the script. Keep the test file unchanged until acceptance completes.

The automated `test_delivery.py` additionally checks the same Nginx location
template with real TLS on an ephemeral loopback port. That certificate is trusted
only by the test client; this is a delivery test, not the remote VM endpoint.

## 2. Freeze acceptance identity

Record separately from the application release:

- Bootstrap version **0.1.0**, Git commit/branch, and SHA-256 from this handoff.
- Actual isolated HTTPS URL and downloaded bootstrap SHA-256.
- Selected published stable release, source commit and package SHA-256.
- Target VM image (Ubuntu 24.04 x86_64), hostname, and IP (private test evidence).

For Freo **0.3.0**, the package SHA-256 must be:

```text
f171ebac1492b6a952787f15515884f3356576bce884640357f83f3bfc292584
```

Its source is `4ff69067e3a3f1b4a488b7ea8f8598ac25a27bda`.
If latest stable has changed, explicitly record and approve the new target;
do not apply 0.3.0's acceptance hash to a different version. `--version 0.3.0`
is available for an explicit stable installation, but test default discovery too.

## 3. Execute the real customer flow on a fresh target

From the **disposable VM**, after substituting the actual staging hostname:

```bash
(set -o pipefail; curl -fsS --proto '=https' --connect-timeout 15 --max-time 120 https://bootstrap-test.example.com/install | sudo bash)
```

Before typing `yes`, verify the screen prominently identifies the intended
hostname, public IP/installation address, OS, architecture, bootstrap version
and selected Freo version. A wrong host/address/version is a reason to cancel.
First check cancellation, then rerun and explicitly confirm on the same still-fresh
VM. Cancellation may leave private discovery evidence but no installed Freo state.

For independent HTTPS acceptance use a **new fresh VM**, a real domain pointing
at it, and explicit `--domain radio.example.com --https --email owner@example.com`.
Do not rerun the fresh installer on an HTTP installation to test HTTPS.

## 4. Operator checks

- One-command download, complete confirmation and stable release discovery.
- Publisher/signature success and `/var/tmp/freo-bootstrap-*/verification.json`.
  Compare `package_sha256` to the approved value above for 0.3.0. This comparison
  is mandatory even though the runtime deliberately has no 0.3.0 hash special case.
- Bundled installation finishes; no automated retries or hidden repairs.
- First login: initial `admin` / `IAmOnTheAir`, then mandatory private password
  and email setup. Do not record the chosen password in acceptance evidence.
- `/admin/software` accessible to the installation admin.
- Installed application version equals the selected release in UI and telemetry.
- Create a station, import music, program/start it, and listen externally.
- `cd /opt/freo && sudo bash scripts/validate-install.sh` passes.
- `sudo systemctl --failed --no-pager` shows no failed units.
- Planned reboot: music and services recover automatically, then validator passes.
- Normal Freo Live heartbeat reports the actual installed version, discovered
  latest stable, and appropriate status (`CURRENT` when they match).
- HTTPS variant: trusted browser certificate, `certbot renew --dry-run`, and
  microphone tests with appropriate WebRTC networking.
- Logs/receipt remain private; success removed temporary application downloads.
- Rerunning the bootstrap on this installed VM stops before installation changes.

If any step fails, preserve evidence and stop. Do not patch/rebuild 0.3.0 or delete
state and retry blindly. A bootstrap-only fix gets new reviewed bootstrap bytes
and another fresh target; an application fix belongs in a later Freo release.

## 5. Publication gate

Record operator acceptance and separately approve activation. Only then copy the
accepted bootstrap bytes and reviewed exact Nginx locations to the production
delivery host. Verify served hashes again. Do not enable the old signed builder,
publish another application release, or rebuild the signed Freo package as part
of activating this delivery mechanism.
