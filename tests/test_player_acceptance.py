"""Public request entry point and station listening PWA boundaries."""
import struct
from app.extensions import db
from app.models import Station
from tests.test_web import app


def test_requests_entry_and_public_pwa(app):
    client=app.test_client()
    page=client.get('/player/test-station').text
    assert 'id="request-open"' not in page and 'id="request-dialog"' not in page
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        station.request_settings={'enabled':True}
        db.session.commit()
    page=client.get('/player/test-station').text
    assert '>REQUESTS</a>' in page and '/requests/test-station' in page
    assert '/player/test-station/manifest.webmanifest' in page
    manifest=client.get('/player/test-station/manifest.webmanifest')
    assert manifest.mimetype=='application/manifest+json'
    data=manifest.json
    assert data['id']==data['start_url']=='/player/test-station'
    assert data['scope']=='/player/' and data['display']=='standalone'
    for icon in data['icons']:
        image=client.get(icon['src'])
        assert image.status_code==200
        assert 'x'.join(map(str,struct.unpack('>II',image.data[16:24])))==icon['sizes']
    assert client.get('/player/no-such-station/manifest.webmanifest').status_code==404
    worker=client.get('/player/sw.js')
    assert worker.status_code==200 and worker.headers['Cache-Control']=='no-cache'
    offline=client.get('/player/offline.html').text
    assert 'You’re offline' in offline and '<audio' not in offline and '<button' not in offline
    assert client.get('/admin/studio.webmanifest').json['scope']=='/admin/'
