"""Traffic plans deterministically and reconciles only confirmed starts."""
from datetime import date,time,datetime,timezone
import uuid,pytest
from app.extensions import db
from app.models import Campaign,CommercialCreative,Track,Station,TrafficLog,TrafficPlacement,TrafficStopset
from app.services.event_blocks import create_execution,prepare_next
from app.services.traffic import (add_rule,add_template_item,attach_creative,cancel_placement,change_placement_creative,
 create_makegood,create_advertiser,create_campaign,create_stopset,finalize_log,generate_log,move_placement)
from tests.test_web import app as app_fixture,admin_client

@pytest.fixture
def app(app_fixture):return app_fixture

def setup_traffic(monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    station=Station.query.filter_by(slug='test-station').first();today=date(2026,9,15)
    asset=Track(uuid=str(uuid.uuid4()),station_id=station.id,title='Thirty',artist='Sponsor',audio_kind='COMMERCIALS',cart_code='ADV-30',original_filename='x.mp3',storage_key='a'*32+'.mp3',media_type='mp3',duration_ms=30000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='f'*64,enabled=True,ingest_status='accepted');db.session.add(asset);db.session.commit()
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
        with pytest.raises(ValueError,match='cross-station'):attach_creative(alien,creative.track.uuid,'Bad','BAD')
    base='/admin/stations/test-station/traffic';anonymous=app.test_client();assert anonymous.get(base).status_code==302 and anonymous.post(base+'/advertiser').status_code==302
    client=admin_client(app);assert client.get(base).status_code==200;assert client.post(base+'/advertiser').status_code==400
    assert client.post(base+'/advertiser',data={'csrf':'test-admin-csrf-token','name':'Web Buyer'}).status_code==303

def test_draft_adjustments_and_finalized_lock(app,monkeypatch):
    with app.app_context():
        station,campaign,_,today=setup_traffic(monkeypatch);log,_=generate_log(station.slug,today);placement=log.placements[0]
        stopsets=TrafficStopset.query.filter_by(station_id=station.id).all();unused=next(s for s in stopsets if s.id not in {p.traffic_stopset_id for p in log.placements})
        old=placement.traffic_stopset_id;move_placement(placement,unused);db.session.commit();assert placement.traffic_stopset_id==unused.id and placement.traffic_stopset_id!=old
        asset=Track(uuid=str(uuid.uuid4()),station_id=station.id,title='Other Thirty',artist='Sponsor',audio_kind='COMMERCIALS',cart_code='ADV-31',original_filename='y.mp3',storage_key='b'*32+'.mp3',media_type='mp3',duration_ms=30000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='e'*64,enabled=True,ingest_status='accepted');db.session.add(asset);db.session.commit()
        other=attach_creative(campaign,asset.uuid,'Other 30','AUTO-31');change_placement_creative(placement,other);db.session.commit();assert placement.commercial_creative_id==other.id
        cancel_placement(placement);db.session.commit();assert placement.status=='CANCELLED'
        finalize_log(log);assert placement.event_block_item_id is None
        with pytest.raises(ValueError,match='immutable'):cancel_placement(next(p for p in log.placements if p.status!='CANCELLED'))

def test_makegood_uses_future_draft_without_rewriting_history(app,monkeypatch):
    from datetime import timedelta
    with app.app_context():
        station,campaign,_,today=setup_traffic(monkeypatch);original_log,_=generate_log(station.slug,today);original=original_log.placements[0];original.status='MISSED';original_log.status='RECONCILED'
        tomorrow=today+timedelta(days=1);campaign.end_date=tomorrow
        for rule in campaign.rules: rule.weekdays=f'{today.weekday()},{tomorrow.weekday()}'
        stopsets=TrafficStopset.query.filter_by(station_id=station.id).all()
        for stop in stopsets: stop.weekdays=f'{today.weekday()},{tomorrow.weekday()}'
        target=TrafficLog(station_id=station.id,log_date=tomorrow,status='DRAFT');db.session.add(target);db.session.commit()
        row=create_makegood(original,target,stopsets[0]);db.session.commit()
        assert row.traffic_log_id==target.id and row.makegood_for_id==original.id and row.is_makegood
        assert original.status=='MISSED' and original.traffic_log.status=='RECONCILED'

def test_log_detail_lifecycle_and_csv_are_protected(app,monkeypatch):
    with app.app_context():
        station,_,_,today=setup_traffic(monkeypatch);log,_=generate_log(station.slug,today);log_date=str(log.log_date)
    client=admin_client(app);base='/admin/stations/test-station/traffic'
    page=client.get(f'{base}/logs/{log_date}');assert page.status_code==200 and b'AS-RUN RECONCILIATION' in page.data and b'Edit placement' in page.data
    csv=client.get(f'{base}/logs/{log_date}/as-run.csv');assert csv.status_code==200 and b'Advertiser,Campaign,Creative' in csv.data and b'/safe' not in csv.data
    assert app.test_client().get(f'{base}/logs/{log_date}').status_code==302
    assert client.post(base+'/advertiser-edit').status_code==400
