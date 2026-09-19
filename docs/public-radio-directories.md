# Public radio directories

Station settings → **Public radio directories** provides two independent,
explicit opt-ins. Both begin OFF/unlisted on existing and new stations. These
features run entirely on the Freo client and do not use freo.live, its tokens,
the Freo directory opt-in, or its synchronization service.

Only an authenticated, active global administrator can change these settings,
using the existing session and CSRF protection. Freo currently has global
administrators rather than station-specific owner roles.

## Radio Browser

Save station settings, then click **List My Station**. Freo sends the station
name and public stream URL, preferred public homepage/player URL, existing PNG
logo, country code, and genre/categories. Unset optional fields are omitted;
Freo currently has no station language field. Contact email, telephone numbers,
Freo credentials and Icecast credentials are not included.

`PUBLIC_BASE_URL` must be an absolute, publicly resolvable HTTP(S) origin with no
path, credentials, query or fragment. Private, loopback, link-local and other
non-global addresses are refused, including hostnames resolving to them. A
verified primary station domain supplies the homepage when configured. Freo
uses the existing public `/listen/<public-name>` or `/stream/<slug>` URL;
the backend's loopback address is never submitted.

Freo discovers a server through Radio Browser's documented DNS SRV record and
POSTs form data to its HTTPS `/json/add` endpoint. DNS discovery is bounded to
3 seconds, connection to 5 seconds and socket reads to 10 seconds, with a 16 KiB
response limit. Redirects and automatic POST retries are disabled. Success
requires `ok: true` and a valid returned UUID, stored on the local station.
**Listed** means the submission succeeded; it does not promise that the
directory's subsequent stream checks will succeed. There is no scheduled
resubmission, metadata synchronization, or removal action.

The server commits a submission claim before contacting Radio Browser, so
double clicks and concurrent requests cannot submit twice. A stored UUID hides
the button and also prevents resubmission on the server. Explicit rejections
and failures before sending show **Error** and allow another user-triggered
attempt. A timeout or malformed reply after sending could mean the remote
station was created: such outcomes disable normal resubmission. An interrupted
process leaves the submission claimed for the same reason.

### Recovering an uncertain submission

An operator must first look up the exact public stream URL in Radio Browser
and verify the returned station UUID. Do not clear a submission claim merely
because a request timed out or a recently added station is not yet visible on
another mirror. After verifying the listing, use a local administrative Flask
shell to record it:

```python
from uuid import UUID
from app.extensions import db
from app.models import Station
station = Station.query.filter_by(slug="YOUR-STATION-SLUG").one()
assert station.radio_browser_uuid is None
assert station.radio_browser_status in ("submitting", "uncertain")
station.radio_browser_uuid = str(UUID("VERIFIED-RADIO-BROWSER-UUID"))
station.radio_browser_status = "listed"
station.radio_browser_error = ""
db.session.commit()
```

If the operator establishes that the add did not occur, they can instead reset
that station's status to `error`, allowing a deliberate retry from settings.
Never use the Freo station UUID as the Radio Browser UUID.

## Internet-Radio.com / Icecast YP

Choose **Public Directory Listing: ON**, then save. The existing root-owned
`freo-provision` service applies this request under its existing provisioning
lock; no additional worker or directory synchronization job is installed. The
page shows the last applied ON/OFF value and any pending or failed operation.
Refresh to check completion. OFF removes that mount from advertising; normal
directory expiry/removal processing can take time. ON describes Icecast's
configuration, not an acceptance receipt from Internet-Radio.com.

Prerequisites:

- Icecast 2.5, an enabled/provisioned station, and a genre or directory categories.
- A public HTTPS domain in `PUBLIC_BASE_URL`, served by Freo's existing proxy.
- A real technical contact email in Icecast's top-level `<admin>` element.
  Icecast sends this contact to YP. This is separate from
  `<authentication><admin-password>`; credentials are never sent. Freo does not
  copy a private station contact email into this setting or invent a contact.
- No other YP directory entries or mount `cluster-password`. Icecast's public
  flag applies across directories; Freo refuses conflicting configurations
  instead of publishing to additional directories implicitly.

Internet-Radio.com documents `http://icecast-yp.internet-radio.com` and a
15-second timeout. A protocol probe on 2026-09-19 confirmed that the HTTP URL
speaks YP, while its HTTPS equivalent redirects to a forum page. Freo therefore
uses the documented HTTP YP URL, carrying public metadata only. Radio Browser
requests and the advertised listener URLs use HTTPS. Icecast 2.5.0 internally
clamps the documented 15-second YP timeout to 6 seconds.

Freo uses Icecast 2.5's `<yp-directory>` with a public virtual listener; the
actual listening socket remains on loopback. Icecast builds listener URLs from
its mount names, so the public `/<internal-slug>` route redirects to the existing
`/stream/<internal-slug>` stream while the station is opted in. Conflicting
public page names are rejected. Existing player and stream URLs keep working.
The bootstrap `localhost` hostname is replaced with the configured public
hostname when enabling YP. It remains public after disabling.

All other mounts, including unconfigured/test sources, explicitly stay private.
Only opted-in mounts receive `<public>1</public>`. Disabling the last listing
leaves the directory and virtual listener dormant so Icecast can send its YP
removal request; all mounts remain private. Source passwords, authentication,
real listening sockets, limits, unrelated mount options and XML comments are
preserved. Provisioning additional stations preserves the directory settings;
new stations remain private. Deleting a station removes its own mount.

Changes are validated as XML and checked against the supported YP/mount/socket
configuration before atomic installation. Icecast has no standalone dry-run
command: actual parser and reload behavior are tested in an isolated instance.
Only changed configuration causes a SIGHUP reload. Application failures restore
the previous file; restoration/reload failures appear in settings. No stream
restart is used. External directory errors belong to Icecast's YP journal and
do not stop streaming. Check `journalctl -u freo-provision` for apply errors and
`journalctl -u icecast2` for directory failures. Do not paste credential-bearing
configuration or debug dumps into public reports.

## Upgrade and validation

Apply migration `a71d25b609ef` with `venv/bin/flask --app wsgi:app db upgrade`
before restarting the updated web/provisioning code. It adds local state only;
it does not publish stations or change the working Icecast file. Review the
migration, public redirect and preserving renderer as part of deployment.
Before rolling back the code/schema, turn Internet-Radio.com OFF and wait for
the change to apply. A Radio Browser listing remains external to Freo even if
the local database migration is reverted.

Focused checks:

```sh
FREO_ENV_FILE=/dev/null venv/bin/pytest -q tests/test_radio_directories.py tests/test_station_lifecycle.py tests/test_station_domains.py tests/test_stations.py
FREO_ENV_FILE=/dev/null FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_radio_directories_engine.py tests/test_station_streams.py
```

The engine test needs local socket/process permissions and installed Icecast
and FFmpeg. It creates temporary sources and a local mock YP endpoint, never
publishes to a real directory, and checks the actual advertised URL, opt-in
isolation, removal, and audio on already-connected listeners across reloads.
Icecast deliberately waits about 60 seconds before a new mount's first add.

Fresh-VM acceptance: provision two stations on Ubuntu 24.04, apply the migration,
verify both directory controls start unpublished, and run the isolated engine
tests. Check the public mount redirect through Nginx and reject a private origin.
Verify provisioning/deleting a third station preserves the others' configuration
and audio. Only explicitly opt in a real station when its owner intends public
publication. Disabling the integration must stop its advertising while the
other station's stream continues.

References: [Radio Browser API](https://docs.radio-browser.info/#add-radio-station),
[server discovery](https://api.radio-browser.info/),
[Internet-Radio.com YP configuration](https://www.internet-radio.com/community/threads/icecast-server-yp-directory-settings.22223/),
[Icecast YP documentation](https://icecast.org/docs/icecast-trunk/yp/),
[Icecast 2.5 listen sockets](https://wiki.xiph.org/Icecast_Server/Listen_Sockets).
