# Installed lifecycle acceptance

Run only on the designated disposable fixture `Freo-v1-Test-1`.
These scripts intentionally stop services, restore customer data, and kill upgrade
or recovery processes. They refuse other hostnames. Do not remove that guard.

- `check.py LABEL`: real status/resources, invalid arguments/non-root rejection,
  failed-worker detection and recovery, application/Icecast restart, encrypted
  backup/verify/list, and live restore of an active backup into a suspended host.
- `interruption.py`: private signed candidate (`FREO_TEST_VERSION`, default `1.0.0-dev.11`), real backup/isolated
  restore, then SIGKILL at the migration boundary. Generic recovery must refuse
  implicit database rollback; explicitly authorized CLI restore must succeed and
  retain suspension. Set `FREO_TEST_SELFHOST=1` for the clean 0.3.2 self-hosted
  case. Uses verified candidate tooling for the initial upgrade, then requires
  recovery through the installed stable CLI.
- `restore_interrupt.py`: SIGKILL immediately after the old database is retained.
  Reboot the disposable host, verify broadcasting is inhibited, invoke
  `freo-admin services recover`, and verify suspension before explicit activation.

Evidence is written under root-private `/root/freo-phase-c`. Publish only sanitized
JSON, never backup keys, credentials, private journals, or subprocess diagnostics.
Run mutation tests sequentially; do not compete with activation checks by compiling
or running the full test suite on this small VM.

Also run existing `hosting_acceptance` listener, storage, and DJ tests and
`upgrade_acceptance` preservation, feature, imaging, and WebRTC checks. Exercise a
clean self-hosted fixture separately and confirm the UI stays commercially silent.
The final report must identify the exact installed artifact and source commit.
