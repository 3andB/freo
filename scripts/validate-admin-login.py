#!/usr/bin/env python3
"""Exercise browser-equivalent cookie/CSRF handling without claiming initial setup."""
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import AdminUser
from app.services.installation_settings import get_setting


def validate():
    app = create_app()
    with app.app_context():
        base = get_setting('PUBLIC_BASE_URL').rstrip('/')
        pending = AdminUser.query.filter_by(username='admin', setup_required=True, active=True).first() is not None
        db.session.remove()
        db.engine.dispose()
    if urlsplit(base).scheme not in ('http', 'https'):
        raise RuntimeError('Saved public origin is missing')
    jar = CookieJar()
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))
    with client.open(base + '/admin/login', timeout=15) as response:
        body = response.read(200000).decode()
        if response.status != 200:
            raise RuntimeError('Login page is unavailable')
    cookies = [cookie for cookie in jar if cookie.name == app.config['SESSION_COOKIE_NAME']]
    if len(cookies) != 1 or cookies[0].secure != (urlsplit(base).scheme == 'https'):
        raise RuntimeError('Login cookie policy does not match the public origin')
    if pending:
        token = re.search(r'name="csrf" value="([^"]+)"', body)
        if not token:
            raise RuntimeError('Login form has no CSRF token')
        from app.services.admin_setup import DEFAULT_PASSWORD
        request = Request(base + '/admin/login', data=urlencode(dict(email='admin', password=DEFAULT_PASSWORD, csrf=token.group(1))).encode())
        with client.open(request, timeout=15) as response:
            if response.status != 200 or urlsplit(response.url).path != '/admin/setup':
                raise RuntimeError('First-use login did not reach setup')
            if 'Complete setup' not in response.read(200000).decode():
                raise RuntimeError('First-use setup form is unavailable')
        print('Initial admin login and mandatory setup verified through the public URL; setup remains unclaimed.')
    else:
        print('Admin login page and session cookie policy verified; existing accounts retained.')


if __name__ == '__main__':
    try:
        validate()
    except Exception:
        raise SystemExit('Admin login validation failed. Check the saved public URL, DNS/TLS, Nginx and session-cookie configuration before handing over this installation.')
