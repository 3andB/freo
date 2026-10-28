# Installed hosting acceptance

These scripts intentionally require hostname `Freo-v1-Test-1` and the existing
Phase A disposable fixture. They are **destructive test harnesses**, not customer
administration commands. Run them as root using the matched application/tooling
Python. Never change the hostname assertion to point at production.

The fixture has original stations `acceptance`, `upgrade-two`, and
`upgrade-stopped`, verified backups, a local PostgreSQL database, Nginx, actual
Icecast/Liquidsoap, and private synthetic credentials. Evidence goes to
`/root/freo-phase-b`. Browser DJ tests use `/root/freo-upgrade-tests/NAME`.
Credentials belong only in root-private files; do not commit them.

- `selfhost.py`: no commercial UI/policy, original authentication, real 192 kbps
  output, and 116 listeners after ordinary Icecast transport tuning.
- `plans.py`: Starter/Pro/Custom, ten concurrent PostgreSQL station allocations,
  rejected downgrade, and supported retirement of the synthetic test stations.
- `listeners.py`: concurrent public/direct connections across two mounts,
  rejection, reconnects, statistics at capacity, and graceful listener reduction.
- `plan-listeners.py`: full Starter 100 and Pro 250 actual listener allowances.
- `bitrate.py`: actual 128 kbps encoder output and rejected conflicting downgrade.
- `storage.py`: concurrent installed writers, decodable capped MP3 recording,
  and uninterrupted audio while over quota.
- `uploads.py`: overlapping actual HTTP requests, abandoned reservation cleanup,
  MP3 ingestion, exact database artwork accounting, and over-quota deletion.
- `dj-quota.py NAME`: Selenium drives the real DJ booth, exhausts quota mid-show,
  verifies broadcast continuity and partial audio, then makes another recording.
- `status.py`: past due, suspension, existing listener disconnect, service restart
  refusal, maintenance, and verified reactivation.
- `interruption.py`: SIGKILL immediately after the durable suspension inhibit.
  Reboot the disposable server, then run `reboot-verify.py`.
- `authority.py`: non-root and invalid-argument JSON errors, customer write
  refusal, missing-policy fail-closed behavior, repair, and explicit activation.
- `recovery.py NAME`: restore/attach the pre-hosting Phase A backup under
  `preserve_authority()`, retaining the displaced database and roots. The old
  application must remain inhibited and activation must refuse incompatible code.
- `fresh-selfhost-fixture.py`: explicitly archives the hosted destination authority
  and uses the retained Phase A test helper to create a **new** self-hosted 0.3.2
  installation. This intentional root-only reset is distinct from customer
  recovery and must never be used by Studio to restore an account.

Run mutation tests sequentially. Browser and compiler/regression loads should not
run alongside activation checks on the two-vCPU test VM. The CLI deliberately
reports failure and retains maintenance when services cannot become healthy within
its verification deadline. Always inspect JSON and exit codes.

Use the standard signed-artifact offline upgrade between the recovery fixture
and the compatible candidate. Do not patch databases or bypass service guards.
Run the Phase A preservation, feature, imaging, and real WebRTC microphone checks
against the installed candidate too. See the linked integration contract and test
report for commands, verified commits, evidence, and operational limits.
