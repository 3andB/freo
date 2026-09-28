#!/usr/bin/env python3
"""Validate local Nginx/login; optionally probe public access separately."""
import argparse
import http.client
from http.cookiejar import CookieJar
from pathlib import Path
import re
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (build_opener, HTTPCookieProcessor, ProxyHandler, Request,
                            HTTPHandler, HTTPSHandler, HTTPRedirectHandler)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ValidationError(RuntimeError):
    """A diagnostic safe to show without credentials, cookies or response bodies."""


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError('Saved public origin must be an HTTP(S) URL without credentials.')
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)


def loopback_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    # Change only the TCP destination. HTTP Host, TLS SNI/certificate hostname,
    # cookie origin and redirect URLs continue to use the saved public URL.
    return socket.create_connection(('127.0.0.1', address[1]), timeout, source_address)


class LocalHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = loopback_connection


class LocalHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = loopback_connection


class LocalHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(LocalHTTPConnection, request)


class LocalHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(LocalHTTPSConnection, request, context=self._context)


class SameOriginRedirects(HTTPRedirectHandler):
    def __init__(self, base):
        self.expected = origin(base)

    def redirect_request(self, request, response, code, message, headers, newurl):
        if origin(newurl) != self.expected:
            raise ValidationError('Redirect left the saved public origin; check the Nginx vhost and saved HTTP/HTTPS URL.')
        return super().redirect_request(request, response, code, message, headers, newurl)


def client_for(base, *, local):
    jar = CookieJar()
    handlers = [ProxyHandler({}), HTTPCookieProcessor(jar), SameOriginRedirects(base)]
    if local:
        handlers += [LocalHTTPHandler(), LocalHTTPSHandler()]
    return build_opener(*handlers), jar


def fetch(client, request, stage, *, timeout=15):
    try:
        with client.open(request, timeout=timeout) as response:
            body = response.read(200000).decode('utf-8')
            if response.status != 200:
                raise ValidationError(f'{stage}: unexpected HTTP status {response.status}.')
            return response.url, body
    except HTTPError as error:
        raise ValidationError(f'{stage}: HTTP {error.code}; check the configured Nginx vhost.') from None
    except (URLError, OSError) as error:
        reason = error.reason if isinstance(error, URLError) else error
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = 'TLS certificate verification failed for the configured hostname'
        elif isinstance(reason, ssl.SSLError):
            detail = 'TLS handshake failed; check the configured HTTPS vhost/SNI'
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            detail = 'connection timed out'
        elif isinstance(reason, socket.gaierror):
            detail = 'public hostname could not be resolved'
        else:
            detail = 'connection failed'
        raise ValidationError(f'{stage}: {detail}.') from None


def validate():
    from app import create_app
    from app.extensions import db
    from app.models import AdminUser
    from app.services.installation_settings import get_setting
    try:
        app = create_app()
        with app.app_context():
            base = get_setting('PUBLIC_BASE_URL').rstrip('/')
            pending = AdminUser.query.filter_by(username='admin', setup_required=True, active=True).first() is not None
            db.session.remove()
            db.engine.dispose()
        scheme, _, _ = origin(base)
    except Exception:
        raise ValidationError('Could not load the saved public origin or administrator state; check installation settings and database readiness.') from None
    client, jar = client_for(base, local=True)
    _, body = fetch(client, base + '/admin/login', 'Login page')
    cookies = [cookie for cookie in jar if cookie.name == app.config['SESSION_COOKIE_NAME']]
    if len(cookies) != 1 or cookies[0].secure != (scheme == 'https'):
        raise ValidationError('Login cookie policy does not match the saved HTTP/HTTPS origin.')
    if pending:
        token = re.search(r'name="csrf" value="([^"]+)"', body)
        if not token:
            raise ValidationError('Login form has no CSRF token.')
        from app.services.admin_setup import DEFAULT_PASSWORD
        request = Request(base + '/admin/login', data=urlencode(dict(email='admin', password=DEFAULT_PASSWORD, csrf=token.group(1))).encode())
        final_url, body = fetch(client, request, 'Initial admin login')
        if origin(final_url) != origin(base) or urlsplit(final_url).path != '/admin/setup':
            raise ValidationError('Initial admin login did not reach mandatory setup; check CSRF/session handling.')
        if 'Complete setup' not in body:
            raise ValidationError('Mandatory setup form is unavailable.')
    return base, pending


def external_access(base):
    # Never send bootstrap credentials to the external endpoint. This is a
    # best-effort reachability check from this VM, not proof from another network.
    client, _ = client_for(base, local=False)
    _, body = fetch(client, base + '/admin/login', 'Public access', timeout=5)
    if not all(f'name="{field}"' in body for field in ('email', 'password', 'csrf')):
        raise ValidationError('Public endpoint did not return the admin sign-in form.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--external', action='store_true', help='Also check public access from this VM; failures are reported separately')
    args = parser.parse_args(argv)
    try:
        base, pending = validate()
    except ValidationError as error:
        print(f'LOCAL APPLICATION VALIDATION — FAILED: {error}', file=sys.stderr)
        return 1
    except Exception:
        print('LOCAL APPLICATION VALIDATION — FAILED: unexpected login validation error; check local application logs.', file=sys.stderr)
        return 1
    account = 'setup remains unclaimed' if pending else 'existing accounts retained'
    print(f'LOCAL APPLICATION VALIDATION — PASSED: Freo/Nginx/admin login; {account}.', flush=True)
    if args.external:
        try:
            external_access(base)
        except ValidationError as error:
            print(f'EXTERNAL ACCESS VALIDATION — NOT CONFIRMED from this VM: {error} Local application validation passed. Open the admin URL from another device; check DNS/firewall or hairpin routing if needed.')
        except Exception:
            print('EXTERNAL ACCESS VALIDATION — NOT CONFIRMED from this VM. Local application validation passed; open the admin URL from another device.')
        else:
            print('EXTERNAL ACCESS VALIDATION — PASSED from this VM (public URL/TLS where enabled). Confirm access from another device.')
    else:
        print('EXTERNAL ACCESS VALIDATION — NOT CHECKED: open the admin URL from another device.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
