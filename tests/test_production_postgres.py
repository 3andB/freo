"""Production migrations and concurrent commands against a disposable cluster only."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from app import create_app, models as m
from app.extensions import db
from app.services import production as service
from tests.test_schedule_postgres import pg_app

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Disposable PostgreSQL required')


def test_full_chain_preserves_phase7(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing');runner=app.test_cli_runner()
    try:
        result=runner.invoke(args=['db','upgrade','f706a1b2c3d4']);assert result.exit_code==0,result.output
        with app.app_context():
            station=m.Station(name='Preserved',slug='preserved',request_settings={'enabled':True});db.session.add(station);db.session.flush()
            db.session.add(m.StationRelay(station_id=station.id,enabled=True,url='https://radio.example/audio'));db.session.commit()
        result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
        with app.app_context():
            assert m.StationRelay.query.one().enabled
            assert m.StationProduction.query.count()==0
            db.session.add(m.StationProduction(station_id=m.Station.query.one().id,enabled=True));db.session.commit()
        for args in (['db','downgrade','f706a1b2c3d4'],['db','upgrade']):
            result=runner.invoke(args=args);assert result.exit_code==0,result.output
        with app.app_context():
            assert m.Station.query.one().request_settings=={'enabled':True}
            assert m.StationRelay.query.one().enabled
            assert m.StationProduction.query.count()==0
    finally:
        with app.app_context():
            db.session.remove();db.drop_all()
            db.session.execute(db.text('DROP TABLE IF EXISTS alembic_version'));db.session.commit();db.engine.dispose()


def test_concurrent_placement_only_one_revision_wins(pg_app):
    from tests.test_production import saved_voice
    with pg_app.app_context():
        station=m.Station.query.one();user=m.AdminUser.query.one()
        row=saved_voice(station,user,'c')
        playlist=m.Playlist(station_id=station.id,name='Granted');db.session.add(playlist);db.session.commit()
        draft_id=row.id;playlist_id=playlist.id;revision=playlist.revision
    barrier=Barrier(2)
    def place(_):
        with pg_app.app_context():
            user=m.AdminUser.query.one();row=db.session.get(m.ProductionDraft,draft_id)
            barrier.wait(timeout=10)
            try:
                service.place(row,user,dict(playlist_id=playlist_id,revision=revision,position=0))
                db.session.commit();return True
            except ValueError:
                db.session.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(place,range(2)))
    assert sorted(results)==[False,True]


def test_concurrent_job_submission_and_assignment_cascade(pg_app):
    with pg_app.app_context():
        station=m.Station.query.one();user=m.AdminUser.query.one()
        row=service.create(station,user,'voice','Link','voice_track');row.components={'voice':'a'*32}
        db.session.commit();identifier=row.id
    barrier=Barrier(2)
    def enqueue(_):
        with pg_app.app_context():
            barrier.wait(timeout=10)
            row=m.ProductionDraft.query.filter_by(id=identifier).with_for_update().first()
            try:
                service.enqueue(row,m.AdminUser.query.one(),'render',{},str(uuid4()),1);db.session.commit();return True
            except ValueError:
                db.session.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(enqueue,range(2)))
    assert sorted(results)==[False,True]
    with pg_app.app_context():
        station=m.Station.query.one();user=m.AdminUser.query.one()
        db.session.add(m.DJStationAssignment(admin_user_id=user.id,station_id=station.id));db.session.flush()
        db.session.add(m.ProductionGrant(user_id=user.id,station_id=station.id,voice_tracking=True));db.session.commit()
        m.DJStationAssignment.query.delete();db.session.commit()
        assert m.ProductionGrant.query.count()==0
