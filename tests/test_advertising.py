"""Campaign display policy and convenience-only audio management."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import random
from werkzeug.datastructures import MultiDict
import pytest
from app.extensions import db
from app.models import (Campaign, CampaignDisplayAsset, CommercialCreative, MediaIngestJob, SelectionDecision,
    Station, StationPlayerSettings, TimedEvent, Track, CampaignScheduleRule)
from app.services import advertising as ads
from tests.test_web import app, admin_client
from tests.test_player_experience import CSRF
from tests.test_station_settings_flags import png

BASE='/admin/stations/test-station/advertising'


def form(**changes):
    values=dict(csrf=CSRF, name='Sponsor', active='yes', priority='100', weight='1', placement='top',
        source='image', destination='https://example.test/sponsor', surfaces=['player'],
        desktop_size='728x90', mobile_size='320x50')
    values.update(changes)
    return values


def create(client, **changes):
    response=client.post(BASE+'/new', data=form(desktop=(BytesIO(png(728,90)), 'banner.png'), **changes))
    assert response.status_code==303, response.text


def test_crud_preserves_traffic_and_audio_state(app):
    client=admin_client(app)
    create(client)
    with app.app_context():
        c=Campaign.query.one();identifier=c.id;revision=c.updated_at.isoformat()
        assert c.status=='DRAFT' and c.advertising['surfaces']==['player']
        before=(SelectionDecision.query.count(), TimedEvent.query.count(), CampaignScheduleRule.query.count())
    page=client.get(BASE)
    assert page.status_code==200 and 'Sponsor' in page.text and 'Active' in page.text
    assert client.post(f'{BASE}/{identifier}', data=form(revision=revision, name='Updated', weight=70)).status_code==303
    assert client.post(f'{BASE}/{identifier}/toggle', data=dict(csrf=CSRF)).status_code==303
    with app.app_context():
        c=db.session.get(Campaign,identifier)
        assert c.status=='DRAFT' and not c.advertising['active']
        assert before==(SelectionDecision.query.count(), TimedEvent.query.count(), CampaignScheduleRule.query.count())
    assert client.post(f'{BASE}/{identifier}/delete',data=dict(csrf=CSRF)).status_code==303
    assert 'Updated' not in client.get(BASE).text
    with app.app_context(): assert Campaign.query.count()==1


def test_priority_weights_surfaces_and_dates(app):
    client=admin_client(app)
    create(client,name='A',priority=10,weight=70)
    create(client,name='B',priority=10,weight=30)
    create(client,name='Lower',priority=9,weight=10000)
    with app.test_request_context():
        station=Station.query.filter_by(slug='test-station').one()
        a,b,lower=Campaign.query.order_by(Campaign.id).all()
        rng=random.Random(12)
        selected=[ads.select(station,'player','top',rng=rng)['campaign_id'] for _ in range(1000)]
        assert 650<selected.count(a.id)<750 and lower.id not in selected
        assert ads.select(station,'homepage','top') is None
        assert ads.select(station,'visualizer','top') is None
        assert ads.select(station,'player','bottom') is None
        assert ads.select(station,'player','top',current=b.id)['campaign_id']==b.id
        now=datetime.now(timezone.utc)
        for campaign in (a,b):
            cfg=ads.settings(campaign);cfg['end']=(now-timedelta(seconds=1)).isoformat();campaign.advertising=cfg
        db.session.commit()
        assert ads.select(station,'player','top')['campaign_id']==lower.id
        cfg=ads.settings(lower);cfg['start']=(now+timedelta(days=1)).isoformat();lower.advertising=cfg;db.session.commit()
        assert ads.select(station,'player','top') is None


@pytest.mark.parametrize('values,expected',[
    ({'active':False},'Disabled'), ({'start':'2030-01-01T00:00:00+00:00'},'Scheduled'),
    ({'end':'2026-01-01T00:00:00+00:00'},'Expired'),({},'Active')])
def test_status(values,expected):
    assert ads.status(dict(ads.DEFAULTS,**values),datetime(2026,1,1,tzinfo=timezone.utc))==expected


@pytest.mark.parametrize('device,size,placement,valid',[
    ('desktop',(728,90),'top',True),('desktop',(970,90),'top',True),('mobile',(320,50),'top',True),
    ('desktop',(300,250),'bottom',True),('mobile',(300,250),'bottom',True),
    ('desktop',(300,250),'top',False),('mobile',(728,90),'top',False),('desktop',(728,91),'top',False)])
def test_dimensions(app,device,size,placement,valid):
    response=admin_client(app).post(BASE+'/new',data=form(placement=placement,**{device:(BytesIO(png(*size)),'ad.png')}))
    assert response.status_code==(303 if valid else 400)
    with app.app_context(): assert CampaignDisplayAsset.query.count()==int(valid)


@pytest.mark.parametrize('changes',[
    dict(weight=0), dict(priority='bad'),dict(surfaces=['unknown']),dict(destination='javascript:alert(1)'),
    dict(start='2026-01-02T00:00',end='2026-01-01T00:00'),dict(source='iframe',iframe='http://example.test'),
    dict(source='google',unit='broken'),dict(desktop=(BytesIO(b'x'* (10*1024*1024+1)),'big.png'))])
def test_validation(app,changes):
    assert admin_client(app).post(BASE+'/new',data=form(**changes)).status_code==400
    with app.app_context(): assert Campaign.query.count()==0


def test_audio_link_replace_remove_and_no_scheduling(app):
    client=admin_client(app)
    with app.app_context():
        track=Track.query.first();track.audio_kind='COMMERCIALS';db.session.commit();tid=track.id
        before=(SelectionDecision.query.count(),TimedEvent.query.count())
    create(client,audio_track_id=tid,surfaces=[])
    with app.app_context():
        c=Campaign.query.one();identifier=c.id;revision=c.updated_at.isoformat()
        assert ads.audio_link(c)[0].id==tid and CommercialCreative.query.count()==0
        assert before==(SelectionDecision.query.count(),TimedEvent.query.count())
    response=client.get(f'{BASE}/{identifier}')
    assert response.status_code==200 and '/audition' in response.text
    assert client.post(f'{BASE}/{identifier}',data=form(revision=revision,remove_audio='yes')).status_code==303
    with app.app_context():
        assert ads.audio_link(Campaign.query.one())==(None,None)
        assert db.session.get(Track,tid) and CommercialCreative.query.count()==0
        assert before==(SelectionDecision.query.count(),TimedEvent.query.count())


def test_upload_is_normal_disabled_commercial_ingest(app,tmp_path):
    app.config['FREO_UPLOAD_ROOT']=str(tmp_path)
    client=admin_client(app)
    create(client,audio=(BytesIO(b'invalid audio'),'commercial.mp3'))
    with app.app_context():
        job=MediaIngestJob.query.one()
        assert job.import_metadata['audio_kind']=='COMMERCIALS' and job.import_metadata['keep_disabled']
        assert ads.audio_link(Campaign.query.one())[1].id==job.id
        from app.ingest_worker import process_one
        process_one()
        assert job.status=='rejected'
        assert SelectionDecision.query.count()==1 and TimedEvent.query.count()==0


def test_authorization_and_settings_link(app):
    client=admin_client(app);create(client)
    with app.app_context(): identifier=Campaign.query.one().id
    assert app.test_client().get(BASE).status_code==302
    assert client.post(f'{BASE}/{identifier}/toggle').status_code==400
    assert client.get(f'/admin/stations/second-station/advertising/{identifier}').status_code==404
    response=client.get('/admin/stations/test-station/settings')
    assert 'Manage Advertising' in response.text and 'Desktop Top Banner' not in response.text
    assert app.test_client().get('/api/stations/test-station/advertising/player/top').json['ad']['campaign_id']==identifier
    assert app.test_client().get('/api/stations/second-station/advertising/player/top').json['ad'] is None


def test_network_and_surface_contract(app):
    client=admin_client(app)
    assert client.post(BASE+'/new',data=form(source='google',unit='/1234/sponsor',surfaces=['homepage','player','visualizer'])).status_code==303
    for surface in ads.SURFACES:
        data=app.test_client().get(f'/api/stations/test-station/advertising/{surface}/top').json['ad']
        assert data['source']=='google' and data['unit']=='/1234/sponsor'
    assert app.test_client().get('/api/stations/test-station/advertising/player/bottom').json['ad'] is None
    assert 'securepubads.g.doubleclick.net' not in client.get(BASE).headers['Content-Security-Policy']


def test_valid_upload_ingests_and_previews_without_scheduling(app,tmp_path,monkeypatch):
    import subprocess
    root=tmp_path/'uploads';root.mkdir();app.config['FREO_UPLOAD_ROOT']=str(root)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    source=tmp_path/'commercial.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=630:duration=1','-y',str(source)],check=True)
    client=admin_client(app)
    create(client,surfaces=[],audio=(BytesIO(source.read_bytes()),'commercial.wav'))
    with app.app_context():
        from app.ingest_worker import process_one
        process_one()
        track,job=ads.audio_link(Campaign.query.one())
        assert job.status=='accepted', job.error_code
        assert track and track.audio_kind=='COMMERCIALS' and not track.enabled
        assert not track.auto_enable_pending
        identifier=track.uuid
        assert TimedEvent.query.count()==0 and SelectionDecision.query.count()==1
    response=client.get('/admin/stations/test-station/media/'+identifier+'/audition')
    assert response.status_code==200


def test_timezone_boundaries_and_stale_edits(app):
    client=admin_client(app)
    with app.app_context():
        s=Station.query.filter_by(slug='test-station').one();s.timezone='Australia/Perth';db.session.commit()
    create(client,start='2026-10-07T10:00',end='2026-10-07T11:00')
    with app.app_context():
        c=Campaign.query.one();identifier=c.id;cfg=ads.settings(c)
        assert cfg['start']=='2026-10-07T02:00:00+00:00'
        assert ads.status(cfg,datetime(2026,10,7,2,tzinfo=timezone.utc))=='Active'
        assert ads.status(cfg,datetime(2026,10,7,3,tzinfo=timezone.utc))=='Expired'
    assert client.post(f'{BASE}/{identifier}',data=form(revision='stale')).status_code==400


def test_existing_traffic_creative_preserved_when_display_link_changes(app,monkeypatch):
    from tests.test_traffic import setup_traffic
    client=admin_client(app)
    with app.app_context():
        station,campaign,creative,today=setup_traffic(monkeypatch)
        cid=campaign.id;tid=creative.track_id;revision=campaign.updated_at.isoformat()
        assert ads.audio_link(campaign)[0].id==tid
        before=(campaign.status,campaign.priority,campaign.start_date,campaign.end_date,len(campaign.rules))
    assert client.post(f'{BASE}/{cid}',data=form(revision=revision,audio_track_id=tid,priority=9,active='')).status_code==303
    with app.app_context():
        c=db.session.get(Campaign,cid)
        assert (c.status,c.priority,c.start_date,c.end_date,len(c.rules))==before
        assert CommercialCreative.query.count()==1 and c.creatives[0].enabled
        revision=c.updated_at.isoformat()
    assert client.post(f'{BASE}/{cid}',data=form(revision=revision,remove_audio='yes')).status_code==303
    with app.app_context():
        c=db.session.get(Campaign,cid)
        assert ads.audio_link(c)==(None,None)
        assert CommercialCreative.query.count()==1 and c.creatives[0].enabled
