# Stable production baseline — 4 October 2026

Production is Freo **0.3.2**. This freeze records the existing installation;
it does not deploy code, change configuration, migrate the database, or restart
services. Main remains the stable production line. Next-major-version work
starts on `develop/v1`.

## Verified identity

| Item | Value |
| --- | --- |
| Production source | `83200e6508654bea13f404e9d5699a8ad3eae19d` |
| Published source tag | `v0.3.2` (unchanged) |
| Annotated freeze tag | `production/v0.3.2-2026-10-04`, at the production source commit |
| Main before this documentation commit | `02b9fc653c7d40745f969f71cdebbc609f64117d` |
| Remote/default branch | `origin/main`; GitHub HEAD points to `main` |
| Runtime symlink | `/opt/freo/current` → `/opt/freo/releases/9d16aee743ab4ad3adaf5eddec4725ae` |
| Artifact platform | Ubuntu 24.04 x86_64; Python 3.12; release format 1; development false |
| Live database server | PostgreSQL 16.15 (`16.15-0ubuntu0.24.04.1`) |
| Live Alembic revision | `c83d4e5f9012` |

Production runs an installed signed artifact, not a Git branch checkout.
`/opt/freo` is a separate source checkout on `main`. Local and remote main
matched at inspection. Main was two commits ahead of the production source;
the differences were documentation and `.gitignore` only. This freeze adds
documentation only. Both installed and main migration heads match the live
database revision. The revision was read in a read-only database transaction;
this is not a full schema-drift audit.

All 448 installed manifest entries matched their SHA-256, size, and permissions.
`freo.service` was active/running with working directory `/opt/freo/current`.
Managed application service definitions use that runtime and
`/etc/freo/freo.env`. The legacy `/etc/freo/release` contains
`4eef2b406906079a0a00f93ea7e3af1cd71367af`; it is stale and must not be used
as the current release identity. It was left unchanged.

## Configuration and artifact fingerprints

The active environment file is `/etc/freo/freo.env`; the retained checkout
`.env` has identical bytes. Non-secret settings observed: `FLASK_ENV=production`,
`FREO_DOMAIN=freo.world`, `PUBLIC_BASE_URL=https://freo.world`,
`FREO_INSTALL_TYPE=self-hosted`, and `FREO_LIVE_MIC=1`. Credentials and other
private runtime values are deliberately excluded from this record.

| Material | SHA-256 |
| --- | --- |
| `/etc/freo/freo.env` | `8cc353754e670602399cb7e000a7c92aa2cdefc1467feb13467f06350a86c763` |
| Installed `release.json` | `27927f4246d474c060833b53e9046f3399ef393a8e4c75699ab64be735004d28` |
| Installed `requirements.lock` | `fbafdb2521130af6f5bb502d66929d3b5a1817460d9d7b10f609df8b0a58c555` |
| `freo-v0.3.2-install-kit.tar` | `2488f8784243fd5bfed4116ea4aff6c0ee6b15f619361379650b7405a269b91a` |
| `freo-v0.3.2.tar.gz` | `7bfc8a573a59dfa210478da9c2b80fccbb0ebcde297a85d4ae56856d96709c4f` |

The archive signature was reverified against publisher fingerprint
`B835B40E7E1A5838390256751AB72B63BEB716C3`. Sixteen published assets, including
the exact installation kit, archive with bundled dependency wheels, detached
signature, publisher key, checksums, acceptance record, and recovery instructions,
were copied from retained downloads to root-only durable storage at
`/var/backups/freo/stable-032-20261004`. Every copied file was hash-checked
against its source. No release archive was rebuilt.

Public copies remain on the [0.3.2 release](https://github.com/3andB/freo/releases/tag/v0.3.2).
The freeze tag is an additional source reference, not a new package or release.
Do not move or overwrite either production tag. The `production/` prefix does
not match the repository's `v*` release-packaging trigger.

## Preservation and recovery

All 14 existing Git worktrees were clean, with no non-ignored untracked files.
Ignored `.env`, `instance/`, `logs/`, `current`, `releases/`, virtual environments,
and existing worktrees are retained. Never use a destructive clean/reset to
prepare this production checkout for development.

Historical recovery material remains at
`/var/backups/freo/production-032-20261001T000518Z`, including the encrypted
pre-upgrade database/filesystem backup, source archive and Git bundle, and
restore-verification evidence. Its passphrase is held separately under
`/root/.config/freo-recovery`. See the
[deployment record](production-0.3.2-2026-10-01.md).

That historical backup predates subsequent user activity; it is not a current
database snapshot. A source tag alone cannot restore user data, media, secrets,
or host configuration. Before any future deployment or rollback, obtain a
separately authorized matched backup of the current database, persistent files,
and configuration, and follow [supported recovery](recovery-and-upgrades.md).
Do not restore the historical database merely to return to this code version.
No new production data snapshot or restore was performed for this freeze.

## Branch policy

- Keep `main` as the stable production line and `/opt/freo` checked out on main.
- Create `develop/v1` at the main commit that introduces this record and the
  matching contribution policy. This gives both lines identical production code
  and baseline documentation at the fork. Do not bump the application version
  as part of establishing the branch.
- Put major updates, architecture changes, and reseller/multi-customer work on
  `develop/v1` or feature branches based on it. Use a separate development
  checkout with isolated configuration, database, storage, and service ports;
  never use the production `.env`, database, runtime symlink, or storage.
- Branch production fixes as `fix/*` from main, review and validate them, then
  merge to main. Port applicable fixes to `develop/v1` separately. Do not merge
  next-major-version work into main while this stable-line policy is active.
- Publishing Git refs does not authorize production deployment. Release and
  deployment changes require their own reviewed procedure. Keep existing tags
  immutable; issue a new patch version/tag for a production code fix.

This policy is documented here and in `CONTRIBUTING.md`; this task does not
change hosting branch-protection settings or CI workflows. Existing recovery CI
runs on pushes, and pull requests run the existing validation workflows.
