# Freo 0.3.0-rc.4 acceptance

This candidate is for a fresh Ubuntu 24.04 x86_64 server. Use the signed test kit
and [installation instructions](install-candidate.md). It is not a public stable
release. The installer does not overwrite existing installations; existing sites
use the backed-up, verified-restore upgrade workflow.

## Changes to exercise

- Timezone dropdowns in station creation, settings, programming and reports show
  IANA names with example cities. Existing database timezone values remain intact.
- Calendar, Blocks and Simple workspaces link to **Add hourly repeat**. This uses
  the same durable Events engine in every mode. Choose **Hourly**, minute **:10**,
  audio/playlist, days and hours; preview the next runs, then save. Soft events run
  after the current song; an active microphone stays protected. Existing timezone
  rules handle clock changes; the preview shows the actual upcoming local times.
- Random playlists exhaust eligible songs before beginning a new cycle and avoid
  repeating the last song at the cycle boundary when another song is available.
  Repeated Shows/Blocks keep source progress in the database across runs/restarts.
  A source containing just one playable song necessarily repeats. Explicit song
  placements and separate event/clock schedules keep their own programming intent.
- The player artwork fills the record circle with a centered crop. Missing art
  keeps the existing fallback. Check square and wide cover images on mobile.
- All public channels have equal links at the top. Test ten ready channels, long
  names, desktop/mobile layouts and both Listen Now dropdowns. Hidden/deleted
  channels must remain excluded. Ten channels are a layout test, not a license
  change; more than three stations across an owner's installations requires the
  paid license under the existing terms.
- The public footer links “Learn more about Freo Free Radio” to https://freo.live/.
- Website / Homepage Editor → Your channels accepts each channel's homepage image.
  Save draft, preview, publish, replace, remove, and restore an earlier publication.
  These images and publication references are stored in PostgreSQL and included in
  database backup. Draft images must not be accessible anonymously.
- On the admin overview, “Select a station” sits immediately above the station
  monitor buttons, with no overlap or horizontal scrolling on narrow screens.

## Fresh server acceptance

1. Verify signature/checksum; run the rc.4 installer once.
2. Log in using `admin` / `IAmOnTheAir`; replace the initial password during setup.
3. Create channels, upload licensed test audio, configure random playback and an
   hourly event. Verify the browser controls and actual audio at the stream URL.
4. Publish customized homepage images, reboot the server, and confirm settings,
   images, credentials, channels and music remain present; verify streaming again.
5. For a domain installation, verify HTTPS redirects and run
   `sudo certbot renew --dry-run`.
6. Separately exercise an upgrade with populated data and the mandatory verified
   backup/restore. A successful fresh installation does not prove upgrade recovery.

Local regression and browser results accompany the signed kit in validation.json.
Host installation/reboot, public certificate issuance, and external audio checks
must be recorded on the new server before approving public distribution.
