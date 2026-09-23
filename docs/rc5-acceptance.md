# Freo 0.3.0-rc.5: fresh installation acceptance

RC.5 includes all RC.4 features plus the fixes below. This is a private test
candidate for a separate Ubuntu 24.04 x86_64 VM, pending owner acceptance.

## What changed

- HTTP IP-only administration now generates UUIDs using browser cryptographic
  randomness even where `crypto.randomUUID` is unavailable. This covers music
  imports, catalog selectors, dialogs, schedules, mode switches and DJ controls.
- An empty music importer no longer overlays its file picker with the action
  toolbar. Loading and initialization errors are visible, with a retry action.
- The first station's monitor appears while setup is pending. Header monitors
  discover new stations and update readiness without a reload; desktop and mobile
  layouts keep the station prompt above the controls.
- The master switch has a BROADCAST caption and an invitation to go on air.
  Starting is disabled while setup is pending and becomes available automatically.
- Provisioning explicitly sets configuration directory permissions despite the
  worker's private umask. Configurations are validated as `freo-playout` before
  setup is marked ready. Config files remain 0640 and private credentials 0600.
- The overview displays the local free-three/perpetual-unlimited license rather
  than obsolete two-station entitlements returned by the remote API.

## Install and identify the exact build

Follow [install-candidate.md](install-candidate.md), including signature and
checksum verification. The inner archive contains `release.json` with its exact
commit and file hashes. The test kit contains `validation.json` with the build
identity and completed versus pending checks. The kit and application archive
have separate checksums. A branch checkout alone is not the installer artifact.

After installation:

```bash
cd /opt/freo
sudo venv/bin/python -c 'from app.version import VERSION; print(VERSION)'
sudo bash scripts/validate-install.sh
```

The version must be `0.3.0-rc.5`. A stable release reported as `0.1.0` by the
heartbeat does not mean RC.5 is outdated: a private prerelease is not published to
the stable index. The freo.live team must update that index only after approval.
Registration is optional and does not gate local setup or playback.

## Record these checks on the fresh VM

1. Log in with `admin` / `IAmOnTheAir`; set your administrator email and a new
   password of at least 16 characters. Check logout and login again.
2. Create your first station. Confirm its header monitor appears immediately,
   shows Preparing, then becomes available when setup is ready. No permission
   repair commands should be necessary. Add another station and repeat.
3. Open Station Control. Confirm BROADCAST appears below OFF. Turn ON and wait
   for confirmed On Air. With an empty library the fallback tone is expected.
   Listen from a separate browser/device, then test OFF and ON again.
4. Navigate to Music → Import music. Test Choose music, clicking Add your music,
   dropping multiple files, and choosing a folder. Confirm the native picker
   opens and no UUID error appears. Import test audio you are authorized to use.
5. Verify metadata, artwork, categories, actual audio files, preview playback and
   processing. Select the imported music for programming and confirm it is heard
   on the public stream. Test a duplicate import and a failed upload retry.
6. Navigate between overview, Station Control, Music and DJ Booth; refresh the
   page. All station monitors should remain visible. Test phone and desktop widths.
7. Exercise the [RC.4 checklist](rc4-acceptance.md): timezones, hourly events at
   :10, random playback without premature repeats, cover art, channel links,
   Listen Now menus and editable homepage channel images.
8. Reboot the VM. Log in and verify music, settings, images, schedules and station
   state remain present. Verify real playback again.
9. On a domain installation, test HTTPS and `sudo certbot renew --dry-run`.
   An IP-only installation intentionally uses HTTP until a domain is configured.
10. Before public distribution, separately test a populated upgrade and recovery
    using [recovery-and-upgrades.md](recovery-and-upgrades.md). Verify actual media
    bytes as well as database rows, credentials, images, schedules and shuffle state.

## Diagnose failures without reinstalling

The following commands read status and logs. Replace `1` with the station's
internal slug when needed. Do not paste credentials or configuration contents.

```bash
sudo namei -l /etc/freo/radio/stations/1.liq
sudo -u freo-playout test -r /etc/freo/radio/stations/1.liq && echo 'Config readable'
sudo systemctl status freo-playout@1.service --no-pager
sudo journalctl -u freo-provision.service -u freo-playout@1.service -u icecast2.service --since '15 minutes ago' -n 100 --no-pager
sudo journalctl -u freo-ingest.service --since '15 minutes ago' -n 100 --no-pager
```

Automated browser tests exercise a fresh production-config database on non-localhost
HTTP and HTTPS origins. Browser tests simulate completion of station provisioning;
a separate real Icecast/Liquidsoap test provisions under umask 0077 and runs audio
as `freo-playout`. Neither substitutes for a full Ubuntu VM installation, systemd
boot, real public TLS issuance or external listening. Record those VM outcomes
before approving distribution.
