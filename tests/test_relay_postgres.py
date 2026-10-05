"""Phase 7 upgrade/rollback and concurrent edits in disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import pytest
from app import create_app, models as m
from app.extensions import db
from app.services import relay
from tests.test_schedule_postgres import pg_app

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Disposable PostgreSQL required')


def test_relay_full_chain_and_phase6_preservation(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','f606a1b2c3d4']);assert result.exit_code==0,result.output
    with app.app_context():
        station=m.Station(name='Preserved',slug='preserved',request_settings={'enabled':True})
        db.session.add(station);db.session.flush()
        db.session.add(m.ApiCredential(id='a'*32,name='Preserved credential',token_digest='b'*64,scope='read'))
        db.session.commit()
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    with app.app_context():
        assert not relay.describe(m.Station.query.one())['enabled']
        db.session.add(m.StationRelay(station_id=m.Station.query.one().id,enabled=True,url='https://radio.test/audio'));db.session.commit()
    for command in (['db','downgrade','f606a1b2c3d4'],['db','upgrade']):
        result=runner.invoke(args=command);assert result.exit_code==0,result.output
    with app.app_context():
        assert m.Station.query.one().request_settings=={'enabled':True}
        assert m.ApiCredential.query.one().name=='Preserved credential'
        assert m.StationRelay.query.count()==0


@pytest.mark.parametrize('existing',[False,True])
def test_concurrent_relay_edits(pg_app,existing):
    if existing:
        with pg_app.app_context():
            db.session.add(m.StationRelay(station_id=m.Station.query.one().id));db.session.commit()
    barrier=Barrier(2)
    def save(_):
        with pg_app.app_context():
            station=m.Station.query.one();user=m.AdminUser.query.one()
            barrier.wait(timeout=10)
            try:
                relay.save(station,dict(relay_revision=1 if existing else 0,relay_url=''),user)
                db.session.commit();return True
            except ValueError:
                db.session.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,range(2)))
    assert sorted(results)==[False,True]
