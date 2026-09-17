"""The project introduction is useful before any station is provisioned."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from tests.test_app import app


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_homepage_before_database_setup_and_all_product_assets(app):
    response = app.test_client().get('/')  # No tables/stations have been created.
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    page = Page(html)
    ids = [a['id'] for _, a in page.elements if 'id' in a]
    assert len(ids) == len(set(ids))
    assert len([tag for tag, _ in page.elements if tag == 'h1']) == 1
    assert {'music', 'schedule', 'booth', 'statistics', 'listeners', 'capabilities', 'technology', 'install'} <= set(ids)
    for tag, attrs in page.elements:
        if tag == 'a' and attrs.get('href', '').startswith('#'):
            assert attrs['href'][1:] in ids
        for key in ('src', 'data-day', 'data-night', 'data-full-day', 'data-full-night'):
            path = attrs.get(key, '')
            if path.startswith('/static/'):
                assert (Path(app.static_folder) / urlparse(path).path.removeprefix('/static/')).is_file(), path
        if tag == 'img' and attrs.get('src'):
            assert attrs.get('alt') and int(attrs['width']) > 0 and int(attrs['height']) > 0
    assert html.count('data-product-screen=') >= 12
    assert 'Demonstration data' in html and 'optional' in html
    assert 'product-dj.png' not in html and 'product-schedule.png' not in html
    assert 'rel="canonical"' not in html


def test_canonical_uses_configured_origin_not_request_host(app):
    app.config['PUBLIC_BASE_URL'] = 'https://radio.example.test/'
    html = app.test_client().get('/', headers={'Host': 'localhost'}).get_data(as_text=True)
    assert '<link rel="canonical" href="https://radio.example.test/">' in html
    assert 'https://radio.example.test/static/product/booth-night-' in html
    assert 'http://localhost/static/product/' not in html
