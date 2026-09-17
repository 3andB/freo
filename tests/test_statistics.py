"""Accounting invariants and public/private boundaries for station analytics."""
import time
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import inspect
from app.extensions import db
from app.models import (StatsBucket, StatsState, AudiencePresence, GeoReach, GeoBucket,
    StorageSnapshot, SelectionDecision, Station, Track, FeedbackTransition, MusicArtwork, StationLogo, StationPlayerAsset)
from app.services.statistics import aggregate, geography, window, ranking
from app.services.statistics import collect, geo
from app.services.statistics.storage import inventory
from tests.test_web import app, admin_client


def observation(listeners=2, sent=1000, epoch='server', source='mount'):
    return dict(online=True, listeners=listeners, bytes=sent, epoch=epoch, source_epoch=source, clients=[])


def test_counter_integrals_resets_gaps_and_partial_station_total(app):
    with app.app_context():
        ids=[s.id for s in Station.query.order_by(Station.id)]
        first,second=ids
        start=1800000000
        collect.tick({first:observation(),second:observation(3)},start)
        collect.tick({first:observation(4,1300),second:observation(1,1500)},start+15)
        total=db.session.get(StatsBucket,(0,'lifetime',0))
        assert (total.listener_seconds,total.peak,total.bytes_sent,total.transfer_seconds)==(75,5,800,15)
        assert aggregate(first,start,start+15,start+15)['total']['bytes_sent']==300
        # A reset in one channel must not erase measured bytes from another.
        collect.tick({first:observation(4,10,source='new'),second:observation(1,1800)},start+30)
        assert total.bytes_sent==1100 and total.transfer_seconds==15
        collect.tick({first:observation(4,2000,source='new'),second:observation(1,2000)},start+100)
        assert total.bytes_sent==1100 and total.observed_seconds==30
        # A retry is idempotent, including samples and checkpoint counters.
        collect.tick({first:observation(4,4000)},start+100)
        assert total.bytes_sent==1100
        collect.tick({first:dict(online=None,listeners=None,clients=None),second:observation(1,2200)},start+115)
        assert total.bytes_sent==1300 and total.observed_seconds==30


def test_bucket_boundaries_preserve_bytes_and_simultaneous_peak(app):
    with app.app_context():
        collect.accumulate(1,3590,3610,2,True,101)
        db.session.commit()
        assert db.session.get(StatsBucket,(1,'hour',0)).bytes_sent==50
        assert db.session.get(StatsBucket,(1,'hour',3600)).bytes_sent==51
        for resolution in ('minute','hour','month','lifetime'):
            assert sum(r.bytes_sent for r in StatsBucket.query.filter_by(scope=1,resolution=resolution))==101


def test_geography_durable_reach_and_expiring_presence(app):
    with app.app_context():
        place=dict(geo.UNKNOWN,place='perth',country='Australia',country_code='AU',city='Perth',lat=-31.95,lon=115.86)
        collect.presence(1,'website','session',place,3590)
        collect.presence(1,'website','session',place,3600)
        collect.presence(1,'website','session',place,3620)
        db.session.commit()
        assert db.session.get(GeoReach,(1,'website','perth')).sessions==1
        assert db.session.get(GeoBucket,(1,'website','perth',3600)).sessions==1
        assert geography(1,'website','live',0,4000,3621)['total']==1
        assert geography(2,'website','live',0,4000,3621)['total']==0
        assert geography(1,'website','live',0,4000,3800)['total']==0
        assert geography(1,'website','history',3600,4000,4000)['located']==1
        AudiencePresence.query.delete();db.session.commit()
        assert geography(0,'website','all',0,4000,4000)['countries']==1


def test_stream_departure_disappears_before_ttl(app):
    with app.app_context():
        collect.presence(1,'stream','one',geo.UNKNOWN,100)
        db.session.add(StatsState(scope=1,data=dict(online=True,clients_at=115)))
        db.session.commit()
        assert geography(1,'stream','live',0,120,120)['total']==0


def test_yesterday_uses_local_calendar_across_dst():
    now=int(datetime(2026,3,9,12,tzinfo=timezone.utc).timestamp())
    value=window({'range':'yesterday','timezone':'America/New_York'},now=now)
    assert value['end']-value['start']==23*3600
    with pytest.raises(ValueError):window({'timezone':'../../etc/passwd'},now=now)


def test_storage_reads_actual_files_images_and_retained_bytes(app,tmp_path):
    with app.app_context():
        app.config['FREO_MEDIA_ROOT']=str(tmp_path)
        original=tmp_path/'test-station'/'originals';original.mkdir(parents=True)
        (original/'internal.mp3').write_bytes(b'1'*42)
        (original/'retained.mp3').write_bytes(b'2'*10)
        (original/'symlink.mp3').symlink_to('/etc/passwd')
        db.session.add_all([MusicArtwork(id='artwork',station_id=1,image=b'a'*10),
            StationLogo(station_id=1,image=b'b'*20,thumbnail=b'c'*5,version='v'),
            StationPlayerAsset(station_id=1,kind='cover',image=b'd'*30,version='v')])
        value=inventory(1800000000)
        assert value['music']==52 and value['retained']==10 and value['missing']==0
        assert value['artwork']==10 and value['logos']==25 and value['player_images']==30
        assert db.session.get(StorageSnapshot,(1,1800000000//3600*3600)).data['total']==117


def test_private_routes_channel_isolation_and_csv(app):
    with app.app_context():
        SelectionDecision.query.update({'started_at':datetime.now(timezone.utc)-timedelta(seconds=2)})
        db.session.commit()
    public=app.test_client()
    assert public.get('/admin/stats/data').status_code==302
    client=admin_client(app)
    for path in ['/admin/stats','/admin/stations/test-station/stats']:
        page=client.get(path)
        assert page.status_code==200 and b'id="stats-map"' in page.data
        response=client.get(path+'/data?compare=1')
        assert response.status_code==200
        assert response.json['music']['plays']==1
        assert response.json['previous_timeline'] is not None
        assert response.headers['Cache-Control']=='private, no-store'
    assert client.get('/admin/stations/second-station/stats/data').json['music']['plays']==0
    assert client.get('/admin/stats/data?range=invalid').status_code==400
    with app.app_context():
        Track.query.first().title='=DANGEROUS()';db.session.commit()
    response=client.get('/admin/stats/export.csv')
    assert response.status_code==200 and b"'=DANGEROUS()" in response.data


def test_presence_csrf_admin_exclusion_and_no_raw_address(app,monkeypatch):
    seen=[]
    monkeypatch.setattr(geo,'lookup',lambda address:seen.append(address) or dict(geo.UNKNOWN))
    client=app.test_client()
    path='/api/stations/test-station/presence'
    assert client.post(path).status_code==400
    token=client.get(path).json['csrf']
    assert client.post(path,headers={'X-Presence-CSRF':token,'X-Real-IP':'8.8.8.8'}).status_code==204
    assert seen==['127.0.0.1']  # Untrusted headers cannot forge geography.
    assert client.post(path,headers={'X-Presence-CSRF':token,'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert admin_client(app).get(path).json=={'ignored':True}
    with app.app_context():
        assert AudiencePresence.query.filter_by(source='website').count()==1
        assert '127.0.0.1' not in str([r.geo for r in AudiencePresence.query.all()])
        assert GeoReach.query.one().sessions==1


def test_only_confirmed_starts_and_current_library_rotation(app):
    with app.app_context():
        track=Track.query.first();station=track.station_id
        db.session.add(SelectionDecision(station_id=station,track_id=track.id,status='queued'))
        db.session.commit()
        now=int(time.time())+1
        result=ranking(station,now-86400,now)
        assert result['plays']==1 and result['rotation_coverage']==100
        track.deleted_at=datetime.now(timezone.utc);db.session.commit()
        result=ranking(station,now-86400,now)
        assert result['plays']==1 and result['rotation_coverage'] is None


def test_additive_migration_upgrade_downgrade_preserves_catalog(app):
    with app.app_context():
        tables=[table for table in db.metadata.sorted_tables if table.name.startswith('stats_')]
        db.metadata.drop_all(db.engine,tables=tables)
        db.session.execute(db.text('DROP INDEX ix_decision_stats_started'));db.session.commit()
    runner=app.test_cli_runner()
    for arguments in [('db','stamp','ab92e51c7034'),('db','upgrade','b185c9a027d6'),('db','downgrade','ab92e51c7034'),('db','upgrade','b185c9a027d6')]:
        result=runner.invoke(args=arguments)
        assert result.exit_code==0,result.output
    with app.app_context():
        assert Track.query.count()==1
        assert len([t for t in inspect(db.engine).get_table_names() if t.startswith('stats_')])==9


def test_icecast_25_xml_unknowns_and_instance_epochs():
    from app.services.statistics.icecast import Icecast
    from types import SimpleNamespace
    import xml.etree.ElementTree as ET
    ice=Icecast.__new__(Icecast)
    stations=[SimpleNamespace(id=1,slug='one'),SimpleNamespace(id=2,slug='two')]
    def read(path):
        if path=='/admin/stats':
            return ET.fromstring('<icestats><instance_uuid>server-uuid</instance_uuid><source mount="/one"><instance_uuid>source-uuid</instance_uuid><listeners>1</listeners><total_bytes_sent>1024</total_bytes_sent></source></icestats>')
        return ET.fromstring('<icestats><source mount="/one"><listener id="7"><ip>2001:4860:4860::8888</ip></listener></source></icestats>')
    ice.read=read
    result=ice.observe(stations)
    assert result[1]['epoch']=='server-uuid' and result[1]['source_epoch']=='source-uuid'
    assert result[1]['bytes']==1024 and result[1]['clients'][0]['id']=='7'
    assert result[2]['listeners']==0 and result[2]['online'] is False
    ice.read=lambda _:(_ for _ in ()).throw(OSError())
    assert ice.observe(stations)[1]['listeners'] is None


def test_feedback_transitions_preserve_retry_change_and_clear(app):
    from tests.test_player_experience import enable, vote
    identifier=enable(app)
    client=app.test_client()
    assert vote(client,identifier,1).status_code==200
    assert vote(client,identifier,1,revision=0).status_code==200
    assert vote(client,identifier,-1).status_code==200
    assert vote(client,identifier,0).status_code==200
    with app.app_context():
        changes=FeedbackTransition.query.order_by(FeedbackTransition.id).all()
        assert [(r.old_value,r.new_value) for r in changes]==[(0,1),(1,-1),(-1,0)]
