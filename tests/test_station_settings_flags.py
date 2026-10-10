import io
import struct
import zlib
from datetime import datetime, timezone, timedelta
import uuid
import pytest
from app.extensions import db
from app.models import Station, StationLogo, SongFlag, Track, SelectionDecision, LiveQueueSnapshot, LiveControlCommand
from tests.test_web import app, admin_client

BASE='/admin/stations/test-station/settings'
FLAG='/admin/api/stations/test-station/flags/00000000-0000-4000-8000-000000000001'
CSRF={'csrf':'test-admin-csrf-token'}


def settings(**kwargs):
    return dict(CSRF,name='Coast FM',city='Fremantle',region='WA',contact_email='studio@example.test',phone='+61 8 5555 0100',description='Coastal radio',public_slug='coast-fm',timezone='Australia/Perth',**kwargs)


def png(width=12,height=8):
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x22\x88\xaa'*width)*height))+chunk(b'IEND',b'')


def test_settings_identity_aliases_contact_privacy_and_isolation(app):
    client=admin_client(app)
    assert app.test_client().get(BASE).status_code==302
    assert client.post(BASE,data={}).status_code==400
    assert client.post(BASE,data=settings()).status_code==302
    for path in ['/admin','/admin/stations','/player/coast-fm','/player/test-station']:
        result=client.get(path,follow_redirects=True)
        assert result.status_code==200 and 'Coast FM' in result.text
    public=app.test_client()
    assert 'studio@example.test' not in public.get('/player/coast-fm').text
    assert client.post(BASE,data=settings(publish_contact='yes')).status_code==302
    assert 'studio@example.test' in public.get('/player/coast-fm').text
    data=settings();data['public_slug']='coast-two'
    assert client.post(BASE,data=data).status_code==302
    assert public.get('/player/coast-fm').status_code==200
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        assert station.city=='Fremantle' and station.region=='WA'
        assert station.timezone=='Australia/Perth'
        assert Station.query.filter_by(slug='second-station').one().city==''


@pytest.mark.parametrize('field,value',[('name',''),('city','x'*121),('contact_email','bad-email'),('public_slug','second-station'),('public_slug','../unsafe'),('timezone','Bogus/Timezone')])
def test_invalid_settings_atomic(app,field,value):
    client=admin_client(app);data=settings();data[field]=value
    assert client.post(BASE,data=data).status_code==400
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        assert station.name=='Test Station' and station.city=='' and station.public_slug is None


def test_logo_roundtrip_replace_remove_cache_and_validation(app):
    client=admin_client(app)
    assert client.post(BASE,data=settings(logo=(io.BytesIO(png()),'square.png'))).status_code==302
    url='/station-assets/test-station/logo.png'
    result=app.test_client().get(url)
    assert result.status_code==200 and result.mimetype=='image/png'
    assert app.test_client().get(url,headers={'If-None-Match':result.headers['ETag']}).status_code==304
    assert app.test_client().get('/station-assets/coast-fm/logo.png?size=original').status_code==200
    original=result.headers['ETag']
    for raw,name in [(b'<svg/>','fake.png'),(b'\x89PNG\r\n\x1a\ninvalid','bad.png'),(png(3001,1),'wide.png'),(b'x'*(10*1024*1024+1),'huge.jpg')]:
        assert client.post(BASE,data=settings(logo=(io.BytesIO(raw),name))).status_code==400
        assert client.get(url).headers['ETag']==original
    assert client.post(BASE,data=settings(logo=(io.BytesIO(png(20,20)),'new.png'))).status_code==302
    assert client.get(url).headers['ETag']!=original
    assert client.post(BASE,data=settings(remove_logo='yes')).status_code==302
    assert client.get(url).status_code==404


def test_flags_lifecycle_conflict_filters_and_station_isolation(app):
    client=admin_client(app)
    assert app.test_client().get(FLAG).status_code==302
    assert client.post(FLAG,data={}).status_code==400
    assert client.get(FLAG).json=={'flag':None}
    assert client.post(FLAG,data=dict(CSRF,note='Check intro',revision=0)).status_code==200
    assert client.post(FLAG,data=dict(CSRF,note='Overwrite',revision=0)).status_code==409
    result=client.get('/admin/api/stations/test-station/music?flags=open&q=Test').json
    assert result['total']==1 and result['flagged_count']==1 and result['songs'][0]['flag']['note']=='Check intro'
    assert client.post(FLAG,data=dict(CSRF,action='resolve',note='Fixed',revision=1)).status_code==200
    assert client.get('/admin/api/stations/test-station/music?flags=open').json['total']==0
    assert client.get('/admin/api/stations/test-station/music?flags=resolved').json['total']==1
    assert client.post(FLAG,data=dict(CSRF,action='reopen',note='Check again',revision=2)).status_code==200
    assert client.post(FLAG,data=dict(CSRF,note='x'*2001,revision=3)).status_code==409
    with app.app_context():
        track=Track.query.first();track.available_to_all=True;db.session.commit()
    other=FLAG.replace('test-station','second-station')
    assert client.get(other).json['flag'] is None
    assert client.post(other,data=dict(CSRF,note='Other review',revision=0)).status_code==200
    assert client.get(FLAG).json['flag']['note']=='Check again'
    with app.app_context():
        assert SongFlag.query.count()==2
        assert Track.query.first().enabled


def test_captured_flag_survives_song_change_without_cross_station_access(app):
    client=admin_client(app)
    with app.app_context():
        track=Track.query.first();current=SelectionDecision.query.filter_by(status='started').first();decision=current.id
        station=Station.query.filter_by(slug='second-station').one()
        track.station_id=station.id;db.session.commit()
    assert client.post(FLAG,data=dict(CSRF,note='Captured song',revision=0,decision_id=decision)).status_code==200
    assert client.post(FLAG.replace('test-station','missing'),data=dict(CSRF,revision=0,decision_id=decision)).status_code==404


def test_skip_ui_and_duplicate_stale_and_mode_guard(app):
    client=admin_client(app)
    page=client.get('/admin/stations/test-station/live').text
    assert 'id="auto-skip"' in page and 'id="auto-next"' in page and 'id="auto-flag"' in page
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();decision=SelectionDecision.query.filter_by(status='started').one()
        identifier=decision.id
        snapshot=LiveQueueSnapshot(station_id=station.id,current_decision_id=identifier,queued_decision_ids=[],unknown_count=0,observed_at=datetime.now(timezone.utc)-timedelta(seconds=20))
        db.session.add(snapshot);db.session.commit()
    def skip():return client.post('/admin/stations/test-station/live/skip',data=dict(CSRF,expected_decision_id=identifier,nonce=str(uuid.uuid4())),headers={'Accept':'application/json'})
    assert skip().status_code==409
    with app.app_context():
        LiveQueueSnapshot.query.first().observed_at=datetime.now(timezone.utc);db.session.commit()
    assert skip().status_code==200 and skip().status_code==200
    with app.app_context():
        assert LiveControlCommand.query.filter_by(action='SKIP').count()==1
        Station.query.filter_by(slug='test-station').one().automation.operator_mode='DJ_BOOTH';db.session.commit()
    assert skip().status_code==409


def test_public_api_hides_contacts_until_published(app):
    client=admin_client(app)
    client.post(BASE,data=settings())
    data=app.test_client().get('/api/stations/test-station').json
    assert data['city']=='Fremantle' and data['player_path']=='/player/coast-fm'
    assert data['contact_email'] is None and data['phone'] is None
    client.post(BASE,data=settings(publish_contact='yes'))
    assert app.test_client().get('/api/stations/test-station').json['contact_email']=='studio@example.test'


@pytest.mark.parametrize('format',['jpg','webp','png'])
def test_supported_logo_formats_and_maximum_size(app,tmp_path,format):
    import subprocess
    source=tmp_path/'source.png';source.write_bytes(png(3000,3000) if format=='png' else png())
    target=source
    if format!='png':
        target=tmp_path/('logo.'+format)
        subprocess.run(['ffmpeg','-v','error','-i',str(source),'-threads','1',str(target)],check=True)
    client=admin_client(app)
    assert client.post(BASE,data=settings(logo=(io.BytesIO(target.read_bytes()),'logo.'+format))).status_code==302
    with app.app_context():
        assert StationLogo.query.count()==1


def test_logo_privacy_and_deleted_station(app):
    client=admin_client(app)
    client.post(BASE,data=settings(logo=(io.BytesIO(png()),'logo.png')))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.enabled=False;db.session.commit()
    url='/station-assets/test-station/logo.png'
    assert app.test_client().get(url).status_code==404
    assert client.get(url).status_code==200
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.deleted_at=datetime.now(timezone.utc);db.session.commit()
    assert client.get(url).status_code==404
    assert client.get(BASE).status_code==404
    assert client.post(FLAG,data=dict(CSRF,revision=0)).status_code==404


def test_settings_station_switch_posts_to_selected_station(app):
    client=admin_client(app)
    response=client.get(BASE+'?station=second-station')
    assert response.status_code==302 and response.headers['Location'].endswith('/second-station/settings')
    response=client.get(response.headers['Location'])
    assert 'action="/admin/stations/second-station/settings"' in response.text
    data=settings();data['public_slug']='second-public'
    assert client.post('/admin/stations/second-station/settings',data=data).status_code==302
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().name=='Test Station'
        assert Station.query.filter_by(slug='second-station').one().name=='Coast FM'
