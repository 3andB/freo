# Freo Studio release download API

This read-only API runs inside the existing Freo World V1 web process. It serves
only root-approved installation files already staged under `/srv/freo-studio`.
It does not expose the root-private upgrade staging area, installed runtime,
environment, database, backups, or configuration. It is not a management API.

The base URL on an activated HTTPS Freo World V1 host is
`https://<freo-world-host>/api/studio`. Freo World 0.3.2 and the previously
signed `1.0.0-rc.1` kit do not contain this later addition. `1.0.0-rc.2` is the
first candidate intended to include it. The first V1 installation still
needs the existing privileged SSH/bootstrap path; an API running inside V1
cannot bootstrap its own host. Do not point Studio at the current production
0.3.2 URL and assume these routes are live.

## Authentication and responses

Every request, including health, requires `Authorization: Bearer <api_key>` over
HTTPS. Pass the key in the header, never a URL, log, command line, or browser.
The server stores only a SHA-256 digest of the 256-bit random secret. The key
is named **Freo Studio Hosting Manager**. It is printed once when a root
administrator creates or rotates it; store it immediately in Studio's secret
manager. Freo World cannot recover the plaintext later.

| Endpoint | Result |
| --- | --- |
| `GET /api/studio/health` | `{"status":"ok"}` when authentication and the approved inventory work |
| `GET /api/studio/releases` | Approved staged versions and relative manifest URLs |
| `GET /api/studio/releases/{version}/manifest` | Exact filenames, sizes, SHA-256 digests and relative download URLs |
| `GET /api/studio/releases/{version}/download` | The approved signed installation kit; use `?file=signature`, `checksum`, `publisher_key`, or `instructions` for its support files |

Only those five roles are downloadable. Unknown versions and roles return 404;
malformed parameters return 400. Missing/invalid bearer keys return 401, HTTP
returns 403, rate limits return 429 with `Retry-After`, and unsafe or changed
staged material returns 503. Responses are `no-store`. Rate limits are 60
requests per network per minute, 120 per key per minute, and 12 downloads per
key per minute. Logs record route, method, status, key ID and network address;
they do not record tokens or request headers.

Studio should first fetch the manifest, download the kit and support files,
compare the downloaded SHA-256 values to the manifest, then verify the detached
signature against a publisher fingerprint pinned through an independent trusted
channel. For RC1 that fingerprint is
`B835B40E7E1A5838390256751AB72B63BEB716C3`. Downloading `publisher.gpg`
does not itself establish trust. Installation and service operations continue
to use the [restricted SSH contract](v1-rc1-installation.md); this API cannot
execute them.

## Root operator procedure

The already staged RC1 files are in `/srv/freo-studio/rc1`. An operator verifies
the outer kit's checksum and detached signature, then records the approved
version and the exact five file names, byte lengths, and SHA-256 values in
`/srv/freo-studio/approved-releases.json`. Its format is:

```json
{"format":1,"releases":[{"version":"1.0.0-rc.1","directory":"rc1","files":{
  "kit":{"name":"freo-v1.0.0-rc.1-install-kit.tar","size":0,"sha256":"<64 hex characters>"},
  "signature":{"name":"freo-v1.0.0-rc.1-install-kit.tar.asc","size":0,"sha256":"<64 hex characters>"},
  "checksum":{"name":"freo-v1.0.0-rc.1-install-kit.sha256","size":0,"sha256":"<64 hex characters>"},
  "publisher_key":{"name":"publisher.gpg","size":0,"sha256":"<64 hex characters>"},
  "instructions":{"name":"v1-rc1-installation.md","size":0,"sha256":"<64 hex characters>"}
}}]}
```

The zero sizes and placeholder digests above illustrate the schema; they are
not an approval record. The live record must use measured values. Keep the
directory and files root-owned, with no group or world write permission. The
API refuses symlinks, path escapes, unapproved names, changed sizes, or a
download whose bytes do not match the approved digest. Adding files to the
directory alone does not publish them through the API.

On the V1 host, create the first key as root with:

```sh
python3 /opt/freo/scripts/studio-api-key.py create
```

The command emits the key only on that invocation. `list` shows IDs and status
without secret values. For rotation, run `rotate`, switch Studio to the new
key, check `/health`, then run `revoke OLD_KEY_ID`. Revocation takes effect on
the next request. The hash inventory is root-owned at
`/srv/freo-studio/studio-api-keys.json`, mode `0640`, group `freo`. Do not place
this file in the web root or include it in release downloads. Neither creating
a key nor approving a release starts or deploys an application service.
