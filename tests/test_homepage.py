"""Station website publication, privacy, channel eligibility and real library totals."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict
from app.extensions import db
from app.models import (Station, Track, WebsiteSettings, WebsitePublication, WebsiteAsset,
                        StationPlayerSettings, PublicScheduleRevision, LiveQueueSnapshot)
from app.services import website
from tests.test_web import app, admin_client


def form(app, **updates):
    with app.app_context():
        values = website.config(True)
        row = db.session.get(WebsiteSettings, 1)
        data = MultiDict({'csrf':'test-admin-csrf-token', 'revision':str(row.revision if row else 0), 'action':'save'})
    for key, value in values.items():
        if isinstance(value, bool):
            if value:data[key]='yes'
        elif key in ('sections', 'channel_order'):
            data.setlist(key, value)
        elif key != 'socials':data[key]=str(value)
    for key,value in updates.items():
        if isinstance(value,list):data.setlist(key,value)
        else:data[key]=value
    return data


def test_homepage_and_empty_install(app):
    client=app.test_client()
    html=client.get('/').text
    assert 'Test Station' in html and 'Second Station' in html
    assert 'product-screen' not in html and 'Capabilities' not in html
    assert client.get('/stations').location.endswith('/#channels')
    with app.app_context():
        Station.query.update({'enabled':False});db.session.commit()
    html=client.get('/').text
    assert 'Something good is on its way.' in html
    assert 'Songs in the library' not in html
    assert 'Your station' in html


def test_channel_eligibility_feature_fallback_and_sharing_count(app):
    with app.app_context():
        second=Station.query.filter_by(slug='second-station').one()
        first=Station.query.filter_by(slug='test-station').one()
        song=Track.query.one();song.available_to_all=True;db.session.commit()
        with app.test_request_context('/'):
            values=website.defaults();values['featured']=str(second.id)
            result=website.presentation(values)
            assert result['featured']['station'].id==second.id
            assert result['metrics'][0][0]==1  # Shared into both channels, counted once.
            assert len(result['cards'])==2  # Stopped channel remains visible.
            for state in ('pending_create','create_failed','pending_delete','delete_failed'):
                second.lifecycle_state=state;db.session.flush()
                assert website.presentation(values)['featured']['station'].id==first.id
                assert len(website.channels())==1
            second.lifecycle_state='ready';second.stream.enabled=False;db.session.flush()
            assert len(website.channels())==1
            song.enabled=False;db.session.flush()
            assert website.presentation(values)['metrics'][0][0]==0


def test_drafts_publish_restore_and_conflict(app):
    client=admin_client(app);anon=app.test_client()
    payload=form(app,name='Private draft',action='save')
    assert client.post('/admin/website',data=payload).status_code==303
    assert 'Private draft' not in anon.get('/').text
    assert 'Private draft' in client.get('/admin/website/preview').text
    assert client.get('/admin/website/preview').headers['Cache-Control']=='private, no-store'
    assert 'noindex' in client.get('/admin/website/preview').headers['X-Robots-Tag']
    assert anon.get('/admin/website/preview').status_code==302
    assert client.post('/admin/website',data=payload).status_code==409
    assert client.post('/admin/website',data=form(app,action='publish')).status_code==303
    assert 'Private draft' in anon.get('/').text
    with app.app_context():old=WebsitePublication.query.order_by(WebsitePublication.id).first().id
    assert client.post('/admin/website',data=form(app,action='restore',publication=str(old))).status_code==303
    assert 'Private draft' not in anon.get('/').text
    assert client.post('/admin/website',data=form(app,name='Throw away')).status_code==303
    assert client.post('/admin/website',data=form(app,action='discard')).status_code==303
    assert 'Throw away' not in client.get('/admin/website').text


def test_permissions_validation_and_contacts(app):
    client=admin_client(app);anon=app.test_client()
    assert anon.post('/admin/website',data=form(app)).status_code==302
    assert client.post('/admin/website',data={'action':'publish'}).status_code==400
    assert client.post('/admin/website',data=form(app,accent='#ffffff')).status_code==400
    assert client.post('/admin/website',data=form(app,social_label_0='Bad link',social_url_0='javascript:alert(1)')).status_code==400
    assert client.post('/admin/website',data=form(app,announcement_start='2026-10-02T00:00+00:00',announcement_end='2026-10-01T00:00+00:00')).status_code==400
    assert client.post('/admin/website',data=form(app,action='publish',contact_email='private@example.test',about='<script>alert(1)</script>')).status_code==303
    html=anon.get('/').text
    assert 'private@example.test' not in html and '&lt;script&gt;' in html
    assert client.post('/admin/website',data=form(app,action='publish',publish_contact='yes')).status_code==303
    assert 'mailto:private@example.test' in anon.get('/').text
    assert anon.get('/website-theme.css?preview=1').status_code==404


def test_draft_assets_do_not_leak_and_history_keeps_images(app,monkeypatch):
    client=admin_client(app);anon=app.test_client()
    monkeypatch.setattr('app.routes.station_settings.decode_logo',lambda upload,output_limit:(upload.read(),b'small'))
    data=form(app);data['hero']=(BytesIO(b'image-one'),'one.png')
    assert client.post('/admin/website',data=data).status_code==303
    with app.app_context():identifier=db.session.get(WebsiteSettings,1).draft['hero']
    path=f'/website-assets/{identifier}.png'
    assert anon.get(path).status_code==404
    assert anon.get(path+'?preview=1').status_code==404
    assert client.get(path+'?preview=1').data==b'image-one'
    assert client.post('/admin/website',data=form(app,action='publish')).status_code==303
    assert anon.get(path).data==b'image-one'
    data=form(app);data['hero']=(BytesIO(b'image-two'),'two.png')
    assert client.post('/admin/website',data=data).status_code==303
    assert anon.get(path).data==b'image-one'
    assert client.post('/admin/website',data=form(app,action='publish')).status_code==303
    assert anon.get(path).status_code==404
    with app.app_context():
        assert db.session.get(WebsiteAsset,identifier)
        publication=WebsitePublication.query.filter(WebsitePublication.config['hero'].as_string()==identifier).one().id
    assert client.post('/admin/website',data=form(app,action='restore',publication=str(publication))).status_code==303
    assert anon.get(path).data==b'image-one'


def test_public_schedules_and_stale_status(app):
    now=datetime.now(timezone.utc)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        db.session.add(StationPlayerSettings(station_id=station.id,config={'schedule_enabled':True}))
        db.session.add(PublicScheduleRevision(station_id=station.id,config_revision=1,start_date=now.date(),end_date=(now+timedelta(days=1)).date(),entries=[dict(title='Published program',start=(now+timedelta(hours=1)).isoformat(),end=(now+timedelta(hours=2)).isoformat())]))
        db.session.add(LiveQueueSnapshot(station_id=station.id,observed_at=now,broadcast_online=True,broadcast_observed_at=now-timedelta(minutes=1)))
        db.session.commit()
    html=app.test_client().get('/').text
    assert 'Published program' in html and 'Status unavailable' in html
    with app.app_context():
        StationPlayerSettings.query.one().config={'schedule_enabled':False};db.session.commit()
    assert 'Published program' not in app.test_client().get('/').text


def test_metadata_uses_configured_origin_and_bundled_assets(app):
    app.config['PUBLIC_BASE_URL']='https://radio.example.test/'
    html=app.test_client().get('/').text
    assert '<link rel="canonical" href="https://radio.example.test/">' in html
    assert 'https://radio.example.test/static/station/listening-room.webp' in html
    for path in ('station/listening-room.webp','station/listening-room-800.webp','station/identity.svg'):
        assert app.test_client().get('/static/'+path).status_code==200


def test_uploaded_image_decoder_and_invalid_payload(app):
    client=admin_client(app)
    data=form(app)
    data['hero']=(BytesIO(b'not an image'),'bad.png')
    assert client.post('/admin/website',data=data).status_code==400
    data=form(app,action='publish')
    data['hero']=(BytesIO((Path(app.static_folder)/'station/listening-room-800.webp').read_bytes()),'hero.webp')
    assert client.post('/admin/website',data=data).status_code==303
    with app.app_context():identifier=db.session.get(WebsiteSettings,1).published['hero']
    response=app.test_client().get(f'/website-assets/{identifier}.png')
    assert response.mimetype=='image/png' and response.data.startswith(b'\x89PNG')
    assert app.test_client().get(f'/website-assets/{identifier}.png',headers={'If-None-Match':response.headers['ETag']}).status_code==304


def test_custom_domain_cannot_serve_installation_website_assets(app):
    from app.models import StationDomain
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        db.session.add(StationDomain(station_id=station.id,hostname='radio.example.test',verification_token='test-token',enabled=True,verified_at=datetime.now(timezone.utc)))
        db.session.commit()
    client=app.test_client()
    assert client.get('/website-theme.css',headers={'Host':'radio.example.test'}).status_code==404
    assert client.get('/website-assets/unknown.png',headers={'Host':'radio.example.test'}).status_code==404
    assert 'data-station="test-station"' in client.get('/',headers={'Host':'radio.example.test'}).text
