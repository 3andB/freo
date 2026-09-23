# RC.5 merge and publication automation audit — 2026-09-23

Scope: both tracked GitHub workflows on `main` and `feature/install-candidate`,
tracked operational scripts/systemd units, local Git hooks, visible GitHub
repository metadata, and production-host systemd/cron references to Git pulling.
This is an audit only: no main merge, release dispatch, tag push, deployment or
stable/latest publication was performed.

## A merge/push to main

The resulting main push matches `.github/workflows/recovery.yml` without a path
filter. GitHub schedules **Recovery and release checks**, on Ubuntu 24.04 with
read-only repository contents permission. The candidate's workflow performs:

1. Checkout with credentials not persisted, then install isolated dependencies.
2. Settings, artifact, upgrade failure-injection, licensing, first-admin, feature
   and station-permission tests.
3. Real-browser first-use tests over HTTP and HTTPS.
4. Real PostgreSQL migration and encrypted restore tests.
5. Build an **unsigned development source-review archive** and upload the GitHub
   Actions artifact `freo-source-review`, retained for 14 days.

This development review archive is not the frozen signed RC.5 installer/test kit.
The documentation push to the candidate branch triggers the same workflow.
Opening/updating a pull request also triggers these checks; a merge can therefore
be associated with both PR checks and the subsequent main-push run.

A main branch push does **not** match the signed-release workflow's `v*` tag
filter. Neither tracked workflow creates a GitHub Release, uploads assets to a
GitHub Release/website, changes a served stable/latest pointer, accesses the
production server, or restarts production services. Merging makes the candidate
source and documentation the default branch contents of the public repository;
it does not itself install that source on an existing server.

## A version-tag push or manual release dispatch

`.github/workflows/release.yml` runs on `push` of tags matching `v*`, or manual
`workflow_dispatch`. It calls the recovery checks, then uses environment
`release` to build a complete archive, sign it using environment secrets, export
the public key, and generate `SHA256SUMS` and a file named `latest.json` with
versioned GitHub Release URLs. It uploads `freo-signed-release-candidate` as a
GitHub Actions artifact with 30-day retention. It does not publish those URLs or
serve that generated index. Success depends on configured signing secrets.

**Do not push the local RC.5 tag under this workflow.** That would request another
build/signing operation for a version whose accepted bytes are frozen. A future
approved publication procedure must upload the existing verified bytes and
preserve their source/tag identity, without rebuilding. Any workflow change to
support that must be reviewed separately; none was made during this deep save.

## Other automation and visibility limits

The read-only GitHub API returned:

- Repository public; default branch `main`; `has_pages: false`.
- Exactly the two workflows above, both active.
- No environments returned and no repository rulesets returned at audit time.
  Do not assume the documented owner-review gate for environment `release` is
  configured or enforced. Organization policies were not available for audit.
- Pages endpoint: HTTP 404, consistent with the repository metadata.
- Webhook listing: HTTP 401. No authenticated GitHub administration API access
  was available; working SSH Git access does not grant that API visibility.

Consequently, installed GitHub Apps, private webhook destinations, external
hosting integrations, organization rules/automation, and website-team jobs
cannot be ruled out. This audit does not claim that a main merge has no external
side effects. Verify those settings with repository/hosting administrators before
requesting final merge approval. No credentials or webhook URLs were collected.

No additional tracked CI configuration was found. The candidate clone has only
sample local Git hooks and no custom `core.hooksPath`. Production systemd/cron
searches found no Git pull/fetch deployment reference. This does not cover
remote hosting systems or the retained test VM, which was not inspected here.

The tracked `freo-updater.timer` invokes `freo_ops.web_updates` to execute queued,
installation-admin-approved upgrade plans. It does not follow a Git branch.
Plans use explicit verified release artifacts and required backup/restore
verification. The freo.live website/API is separately managed by its team;
merging this repository is not its documented publication mechanism.

## Recommendation

Keep RC.5 as the accepted, frozen private baseline. First verify the inaccessible
external integrations and arrange populated upgrade/restore acceptance on a
separate clone of the retained VM. Review a source merge independently from
release publication. Obtain owner approval before either step. For any later
public RC.5 prerelease, publish only the existing signed bytes through a reviewed
procedure that avoids rebuilding them; keep prereleases out of stable/latest.
