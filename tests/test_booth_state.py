import uuid
from datetime import datetime,timezone,timedelta
import pytest
from app.extensions import db
from app.models import Station,Track,AdminUser,SelectionDecision,LiveQueueSnapshot,LiveCartSlot
from app.services.live_assist import fire_cart,status,request_skip
from tests.test_web import app,admin_client


def prepare(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    station=Station.query.filter_by(slug='test-station').one();song=Track.query.first()
    snapshot=LiveQueueSnapshot(station_id=station.id,observed_at=datetime.now(timezone.utc),queued_decision_ids=[],mixer={'mode':'AUTO','cart_id':None},unknown_count=0)
    db.session.add(snapshot)
    for role,pos in [('HOT',1),('ID',1)]:db.session.add(LiveCartSlot(station_id=station.id,role=role,position=pos,track_id=song.id,label='Same audio'))
    db.session.commit()
    return station,snapshot,AdminUser.query.first()


def test_cart_lock_identity_idempotence_completion_failure_and_stale(app,monkeypatch):
    with app.app_context():
        station,snapshot,user=prepare(app,monkeypatch)
        nonce=str(uuid.uuid4());cart=fire_cart(station,user,'HOT',1,nonce)
        assert fire_cart(station,user,'HOT',1,nonce).id==cart.id
        with pytest.raises(ValueError,match='already queued'):fire_cart(station,user,'ID',1,str(uuid.uuid4()))
        observed=status(station)['cart'];assert observed['locked'] and observed['role']=='HOT' and observed['position']==1 and observed['state']=='queued'
        cart.status='started';cart.started_at=datetime.now(timezone.utc);db.session.commit()
        # No gap between start confirmation and the next mixer snapshot.
        assert status(station)['cart']['locked']
        with pytest.raises(ValueError):fire_cart(station,user,'ID',1,str(uuid.uuid4()))
        snapshot.mixer={'mode':'AUTO','cart_id':cart.id};snapshot.observed_at=datetime.now(timezone.utc);db.session.commit()
        assert status(station)['cart']['state']=='playing'
        snapshot.mixer={'mode':'AUTO','cart_id':None};snapshot.observed_at=datetime.now(timezone.utc);db.session.commit()
        assert not status(station)['cart']['locked']
        second=fire_cart(station,user,'ID',1,str(uuid.uuid4()));assert second.cart_role=='ID'
        second.status='failed';second.reason='manual_queue_failed';db.session.commit()
        assert not status(station)['cart']['locked'] and status(station)['cart_result']['status']=='failed'
        snapshot.observed_at=datetime.now(timezone.utc)-timedelta(seconds=20);db.session.commit()
        assert status(station)['cart']['locked']
        with pytest.raises(ValueError):fire_cart(station,user,'HOT',1,str(uuid.uuid4()))


def test_cart_locks_are_station_scoped_and_skip_cannot_fade_cart(app,monkeypatch):
    with app.app_context():
        station,snapshot,user=prepare(app,monkeypatch)
        other=Station.query.filter_by(slug='second-station').one()
        db.session.add(SelectionDecision(station_id=other.id,track_id=Track.query.first().id,playback_bus='CART',status='selected'))
        db.session.commit()
        cart=fire_cart(station,user,'HOT',1,str(uuid.uuid4()))
        cart.status='started';cart.started_at=datetime.now(timezone.utc);snapshot.current_decision_id=cart.id;db.session.commit()
        with pytest.raises(ValueError):request_skip(station,user,cart.id,str(uuid.uuid4()))


def test_status_has_category_program_and_fresh_broadcast_metrics(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();decision=SelectionDecision.query.filter_by(status='started').one()
        snapshot=LiveQueueSnapshot(station_id=station.id,observed_at=datetime.now(timezone.utc),current_decision_id=decision.id,queued_decision_ids=[],unknown_count=0,
            broadcast_online=True,listeners=7,broadcast_observed_at=datetime.now(timezone.utc))
        db.session.add(snapshot);db.session.commit()
        observed=status(station)
        assert observed['current']['category']=='Power' and observed['program']
        assert observed['broadcast']=={'online':True,'listeners':7}
        snapshot.broadcast_observed_at=datetime.now(timezone.utc)-timedelta(seconds=20);db.session.commit()
        assert status(station)['broadcast']=={'online':None,'listeners':None}
    text=admin_client(app).get('/admin/stations/test-station/live').text
    assert 'id="auto-clock"' not in text and 'id="auto-category"' in text
    assert 'aria-live="polite" hidden></p>' not in text


def test_broadcast_metrics_cache_mount_isolation_and_failure(monkeypatch):
    from app.services import broadcast_status as service
    import io
    calls=[]
    monkeypatch.setattr(service,'_checked',0.0)
    def open_stats(*args,**kwargs):
        calls.append(1)
        return io.BytesIO(b'{"icestats":{"source":[{"listenurl":"http://localhost:8001/one","listeners":8},{"listenurl":"http://localhost:8001/two","listeners":3}]}}')
    monkeypatch.setattr(service._opener,'open',open_stats)
    assert service.observation('one')==(True,8)
    assert service.observation('two')==(True,3)
    assert service.observation('absent')==(False,0) and len(calls)==1
    monkeypatch.setattr(service,'_checked',0.0)
    monkeypatch.setattr(service._opener,'open',lambda *a,**k:(_ for _ in ()).throw(OSError('offline')))
    assert service.observation('one')==(None,None)
