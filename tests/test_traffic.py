"""Traffic plans deterministically and reconciles only confirmed starts."""
from datetime import date,time,datetime,timezone
import uuid,pytest
from app.extensions import db
from app.models import Campaign,ImagingAsset,Station
from app.services.event_blocks import create_execution,prepare_next
from app.services.traffic import (add_rule,add_template_item,attach_creative,create_advertiser,create_campaign,
 create_stopset,finalize_log,generate_log)
from tests.test_web import app as app_fixture,admin_client

@pytest.fixture
def app(app_fixture):return app_fixture

def setup_traffic(monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.imaging_file',lambda *a:'/safe')
    station=Station.query.filter_by(slug='test-station').first();today=date(2026,9,15)
    asset=ImagingAsset(uuid=str(uuid.uuid4()),station_id=station.id,name='Thirty',cart_code='ADV-30',asset_type='COMMERCIAL',original_filename='x.mp3',storage_key='a'*32+'.mp3',media_type='mp3',duration_ms=30000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='f'*64,enabled=True,ingest_status='accepted');db.session.add(asset);db.session.commit()
    advertiser=create_advertiser(station.slug,'Local Auto');campaign=create_campaign(station.slug,advertiser.slug,'September Drive',today,today,target=2,priority=200);campaign.status='ACTIVE';db.session.commit();creative=attach_creative(campaign,asset.uuid,'Auto 30','AUTO-30')
    add_rule(campaign,[today.weekday()],time(8),time(18),2,minimum=3600)
    for n,hour in enumerate((9,12,16)):
        stop=create_stopset(station.slug,f'Break {n}',[today.weekday()],time(hour,20),60,max_spots=1);add_template_item(stop,'COMMERCIAL_SLOT')
    return station,campaign,creative,today

def test_distribution_capacity_finalization_and_immutability(app,monkeypatch):
    with app.app_context():
        station,_,_,today=setup_traffic(monkeypatch);log,report=generate_log(station.slug,today)
        assert report==[{'campaign':'September Drive','requested':2,'scheduled':2,'unscheduled':0}]
        first=[(p.traffic_stopset_id,p.commercial_creative_id,p.position) for p in log.placements]
        log,_=generate_log(station.slug,today);assert first==[(p.traffic_stopset_id,p.commercial_creative_id,p.position) for p in log.placements]
        finalize_log(log);assert log.status=='FINALIZED' and all(p.status=='MATERIALIZED' and p.event_block_item_id for p in log.placements)
        assert len({p.traffic_stopset_id for p in log.placements})==2
        with pytest.raises(ValueError,match='immutable'):generate_log(station.slug,today)

def test_only_confirmed_block_start_marks_placement_aired(app,monkeypatch):
    from app.services.automation import playback_started
    with app.app_context():
        station,_,_,today=setup_traffic(monkeypatch);log,_=generate_log(station.slug,today);finalize_log(log);placement=log.placements[0]
        event=next(e for e in station.event_blocks if e.slug.endswith(placement.stopset.slug));run=create_execution(event,'MANUAL');item=prepare_next(run)
        assert placement.status=='MATERIALIZED';started=datetime.now(timezone.utc);assert playback_started(item.selection_decision_id,station.slug,started)
        assert placement.status=='AIRED' and placement.confirmed_started_at.replace(tzinfo=timezone.utc)==started and placement.event_block_item_execution_id==item.id

def test_cross_station_creative_and_admin_security(app,monkeypatch):
    with app.app_context():
        station,campaign,creative,today=setup_traffic(monkeypatch);other=Station.query.filter_by(slug='second-station').first()
        alien=Campaign(station_id=other.id,name='X',slug='x',status='DRAFT',start_date=today,end_date=today,advertiser_id=campaign.advertiser_id)
        with pytest.raises(ValueError,match='cross-station'):attach_creative(alien,creative.imaging_asset.uuid,'Bad','BAD')
    base='/admin/stations/test-station/traffic';anonymous=app.test_client();assert anonymous.get(base).status_code==302 and anonymous.post(base+'/advertiser').status_code==302
    client=admin_client(app);assert client.get(base).status_code==200;assert client.post(base+'/advertiser').status_code==400
    assert client.post(base+'/advertiser',data={'csrf':'test-admin-csrf-token','name':'Web Buyer'}).status_code==303
