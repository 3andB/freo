# Freo 1.0.0

Stable promotion of human-accepted RC17 (`76d1d1769de120dba890d986e424104c4a369ea1`). Application behavior, PostgreSQL schema `fe28c3d4e5f6`, dependency wheels and licensing are retained.

V1 includes station operations, scheduling, DJ and live microphone workflows, public players, hosted lifecycle controls, optional Freo Live reporting, and signed backup/upgrade/recovery tooling. Hosting remains an explicit deployment policy.

Human acceptance was confirmed on 28 October 2026. Retained RC17 qualification covers 1,875 backend cases (214 optional skips), fresh reporting tests and prior browser/migration checks; this was combined qualification rather than one fresh full invocation. Public-page verification passed 19 gates on 26 October. Final signed-package acceptance is recorded separately with artifact hashes; these prior results do not certify newly built bytes.

Use the [stable installation guide](stable-installation.md) for a new Ubuntu 24.04 x86_64 host. Existing 0.3.2 and V1 installations must use the [signed upgrade and matched-backup recovery procedure](recovery-and-upgrades.md). Do not reinstall over existing state or attempt a database downgrade.

Physical microphone devices, remote NAT/TURN, and every customer host configuration are outside automated package acceptance. Historical releases and recovery material remain immutable.
