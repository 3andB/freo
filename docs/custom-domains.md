# Station custom domains

Custom domains add a public web/player address to a station. They do not change
Icecast, Liquidsoap, stream paths, API authorization, or existing station URLs.
The implementation uses the existing global-admin account model: active admins
can manage every station. There are no tenant-specific user roles yet. Every
mutation scopes the domain ID to its station and requires authentication and CSRF.

## Installation configuration

Install `requirements.txt` and run `venv/bin/flask --app wsgi db upgrade` before
restarting Freo. Configure these environment variables:

```
PUBLIC_BASE_URL=https://radio.example.net
FREO_INSTALLATION_HOSTS=radio.example.net,www.radio.example.net,203.0.113.10
FREO_DOMAIN_TARGET_HOST=radio.example.net
FREO_DOMAIN_TARGET_IPS=203.0.113.10,2001:db8::10
```

Replace all example hosts and addresses with the installation's actual public
endpoints. `PUBLIC_BASE_URL` and `FREO_DOMAIN` hosts are also recognized as
installation hosts; list every additional existing hostname or IP explicitly in
`FREO_INSTALLATION_HOSTS`. Localhost is automatically allowed only in development
and tests. Host configuration is never inferred from a request.

Verification accepts addresses configured in `FREO_DOMAIN_TARGET_IPS` or resolved
from `FREO_DOMAIN_TARGET_HOST`. At least one target is required. Every A/AAAA
address of a customer hostname must belong to that set. Use the reverse proxy's
public addresses, not a private Flask backend address. DNS-proxied/CDN hostnames
are unsupported unless their addresses are explicitly approved as installation
targets. The system resolver must work; each DNS query has a three-second limit.

## Add a customer domain

1. Open the station's **Settings → Domains** and add its hostname (no scheme or
   path; international names must use ASCII IDNA/punycode).
2. For `rock.xyz.com`, create `CNAME rock → radio.example.net`. For the apex
   `xyz.com`, create `A @ → server IPv4`; add AAAA only for working server IPv6.
3. Add the displayed `_freo-verification.<hostname>` TXT record with the exact
   `freo-verification=...` value. DNS providers often expect a name relative to
   the zone. The token is unique to this claim; removing and re-adding a domain
   generates a new token. This proves DNS control even on a shared server IP.
4. Wait for propagation and click **Verify**. Success sets `verified_at` and
   enables routing. Failures do not activate a pending domain. A failed later
   recheck preserves an existing successful verification; remove the domain to
   revoke routing. Verification is on demand, not continuous monitoring.
5. Configure HTTPS at the reverse proxy as below, then test the hostname.
6. Optionally set a verified domain as primary. This selects the preferred link
   shown in station settings. It does not redirect other domains. Removing the
   primary restores the original station link until another primary is selected.

No DNS or certificate changes are made by Flask.

## Existing Nginx / Certbot deployment

Keep Nginx. Use `deploy/nginx/custom-domain.conf.template` as a separate site per
customer domain (or a group belonging to the same station). Replace the validated
hostname placeholder, enable the site, run `nginx -t`, then reload Nginx. Install
the same stream/station snippets used by the main Freo site; these preserve
relative player stream URLs, without changing the audio services.

Provision HTTPS with the existing Certbot installation, for example:

```
sudo certbot --nginx -d rock.xyz.com
sudo nginx -t
sudo systemctl reload nginx
```

Keep Certbot renewal enabled. Confirm HTTPS works before distributing the preferred
link. HTTP DNS verification does not prove HTTPS readiness.

Install `deploy/nginx/reject-unknown.conf` as the default site, replacing any
existing default server on those listen addresses rather than defining two.
Nginx 1.19.4+ supports the [TLS handshake rejection](https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_reject_handshake) used by this snippet. Test the
configuration against the installed version first. If you expose IPv6, add matching
`[::]:80` and `[::]:443` listeners to the named and default sites. Keep Gunicorn bound to
loopback or a private proxy-only interface. Preserve `Host` and clear
`X-Forwarded-Host`; do not configure Flask to trust forwarded host headers.
Other reverse proxies should enforce the same explicit hostname and HTTPS rules.

## Routing and security behavior

- Installation hosts retain `/`, `/stations`, `/player/<slug>`, and old aliases.
- Verified/enabled custom hosts show their station player at `/` and `/stations`.
- Station player, listener alias, and logo paths on a custom host must resolve to
  the assigned station, including when an old station slug is used.
- Unknown, pending, disabled, or deleted-station hosts return 404 for public
  station routes. Malformed Host values return 400.
- APIs and admin routes retain their existing routing and authentication. Public
  API data remains public; hostname routing is not a new API permission boundary.
- Static assets and Nginx stream locations retain existing behavior.
- Hostnames choose public content, never an authenticated user or permission.
  Database constraints prevent duplicate claims, multiple primary domains, and
  enabled unverified records. Application writes normalize hostnames.

No customer hostnames or certificates are automatically installed. Removal revokes
Flask routing immediately; the operator should also remove the proxy site and
retire its certificate when appropriate. Successful station deletion also releases
its domain claims; a new claim always requires a fresh TXT token and verification.
Pending or failed station deletion blocks routing but retains the claims for retry.

References: [Nginx request selection](https://nginx.org/en/docs/http/request_processing.html)
and [dnspython resolver timeouts](https://dnspython.readthedocs.io/en/stable/resolver-class.html).
