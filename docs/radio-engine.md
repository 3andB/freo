# Phase 2 radio engine

Ubuntu 24.04 distribution packages are the default: this server has Liquidsoap `2.2.4-1` and Icecast `2.4.4-4build4`. The installer checks the installed packages and validates the Liquidsoap script with `liquidsoap --check`. No OPAM build is required. Package versions may change; a fresh VM must validate each supported release.

One explicit test station, **Freo Test**, generates a quiet 440 Hz sine wave with title **Freo Engine Test**. Liquidsoap sends MP3 to the private Icecast mount `127.0.0.1:8001/freo-test`. Nginx exposes only `https://freo.world/stream/freo-test` on this server. The exact-match proxy does not expose Icecast admin, source, or status endpoints. This is engine proof, not scheduled programming.

`icecast2.service` is Freo's native systemd unit for the Ubuntu package binary and package-managed `icecast2:icecast` account. The package's SysV-generated unit cannot express the private Freo config cleanly; the version-controlled native unit supersedes it without editing package files. `freo-playout.service` runs as the non-login `freo-playout` account after Icecast. Freo web stays independent: a playout failure does not stop the website. systemd restarts failed radio processes. Journald holds service logs; Icecast's access/error logs point to stderr.

The root-only renderer `scripts/render-radio-config.py` reads repository templates, creates random source/relay/admin credentials once in `/etc/freo/secrets/engine.json` (mode `0600`), validates XML and Liquidsoap syntax, backs up prior runtime configs, and atomically installs `/etc/freo/radio/icecast.xml` (`root:icecast`, `0640`) and `/etc/freo/radio/freo-test.liq` (`root:freo-playout`, `0640`). Runtime configs contain secrets and must never enter Git. The source checkout remains root-owned. `/var/lib/freo` is traversable (`0711`) so playout can reach its own `0750` directory without listing Freo state. The private Liquidsoap control socket is `/run/freo/liquidsoap/control.sock`, mode `0600`, within a `0711` directory. It is not exposed on TCP or passed through Flask. The web app observes socket presence and local Icecast responses, never invokes sudo or arbitrary shell commands.

Only SSH 22 and Nginx 80/443 should be public. Gunicorn 8000, PostgreSQL 5432, and Icecast 8001 bind locally. UFW was inactive on this server; no firewall settings were changed. For a fresh install, verify host and cloud firewall rules separately.

Useful checks: `systemctl status icecast2 freo-playout freo`, `journalctl -u freo-playout -n 50`, `ss -ltnp`, `curl https://freo.world/health/icecast`, `curl https://freo.world/health/playout`, and `curl https://freo.world/health/stream`. A player can open the public stream URL. A bounded byte read should return `audio/mpeg` and nonzero audio bytes; an HTTP 200 alone is insufficient. To validate a changed Liquidsoap template, use `liquidsoap --check` before rendering or restarting. Icecast has no config-only validation flag in this package; the renderer parses XML, and service startup plus local status/mount checks complete validation. Keep the previous runtime config and backed-up unit for rollback.

Future multi-station operation should start with one Liquidsoap process/config per station: failure isolation and independent restart make it easier to operate. A single process with multiple outputs uses fewer resources but couples all stations to one process and configuration. Station and mount definitions may later move to PostgreSQL, with validated per-station rendering by a restricted CLI/worker. Phase 2 does not add station schema or web-based service control.

## Managed stations added in Phase 3

`freo-test` remains the fixed engine diagnostic. Database-managed stations use the independent `freo-playout@<slug>.service` unit, mount-specific source credentials, and exact Nginx listener snippets. Icecast remains a single private backend. See [stations.md](stations.md) for lifecycle and isolation details.

## Media playback

Managed stations load only the root-rendered approved playlist for their own slug. The Phase 4 source uses Liquidsoap playlist watch mode and falls back to a generated tone if no playable request is available. Disabling or enabling a track through the CLI refreshes the playlist and restarts only the affected station, so a queued copy cannot continue after disable. The `freo-test` diagnostic source remains independent. No arbitrary Liquidsoap commands or filesystem paths are accepted over HTTP.

## Phase 5 request source

Managed stations now use Liquidsoap `request.queue` with a two-request lookahead supplied by Freo's non-root automation worker. The `freo-test` diagnostic script remains independent. A private per-station `on_track` event file confirms actual starts. The managed control socket is mode 0660 for the restricted worker/playout group; the web account is not a member. See [automation.md](automation.md).
# Time-aware programming

The Phase 6 scheduler chooses a station clock from recurring local weekly assignments. Its slots ask Freo's existing selector for approved tracks, and the worker pushes requests through the private station socket. Liquidsoap remains the audio engine and does not interpret schedules or restart at hour boundaries. See [scheduling](scheduling.md).
