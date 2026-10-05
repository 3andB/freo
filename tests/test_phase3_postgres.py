"""Real migration preservation and concurrent ownership on disposable PostgreSQL."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import AdminUser, Station, LiveSession
from app.services.live_sessions import claim
from tests.test_schedule_postgres import pg_app

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Disposable PostgreSQL required')


def test_full_migration_preserves_admin_access(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','f206a1b2c3d4']);assert result.exit_code==0,result.output
    with app.app_context():
        db.session.execute(sa.text("INSERT INTO admin_users(email,password_hash,active,installation_admin,created_at,setup_required) VALUES ('old@example.test','unused',true,false,now(),false)"));db.session.commit()
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    with app.app_context():
        user=AdminUser.query.filter_by(email='old@example.test').one()
        assert user.role=='ADMIN' and user.active and not user.installation_admin
    result=runner.invoke(args=['db','downgrade','f206a1b2c3d4']);assert result.exit_code==0,result.output
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output


def test_two_simultaneous_claims_have_one_owner(pg_app):
    with pg_app.app_context():
        other=AdminUser(email='other@example.test',password_hash='unused');db.session.add(other);db.session.commit()
        identifiers=[u.id for u in AdminUser.query.order_by(AdminUser.id)]
    barrier=Barrier(2)
    def attempt(identifier):
        with pg_app.app_context():
            station=Station.query.one();user=db.session.get(AdminUser,identifier)
            barrier.wait(timeout=10)
            try:
                show=claim(station,user);db.session.commit();return show.admin_user_id
            except ValueError:
                db.session.rollback();return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,identifiers))
    assert len([value for value in results if value is not None])==1
    with pg_app.app_context():assert LiveSession.query.count()==1


def test_recording_manager_migration_preserves_existing_files_and_history(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','f306a1b2c3d4']);assert result.exit_code==0,result.output
    with app.app_context():
        # Current Station includes Phase 5 fields absent from the Phase 3 schema.
        db.session.execute(sa.text("""INSERT INTO stations
            (id,name,slug,description,enabled,desired_state,timezone,target_lufs,
             freo_station_id,created_at,updated_at)
            VALUES (1,'Migration','migration','',true,'stopped','UTC',-16,
                    '11111111-1111-4111-8111-111111111111',now(),now())"""))
        db.session.execute(sa.text("INSERT INTO live_sessions(id,station_id,dj_name,created_at) VALUES(:id,1,'Original DJ',now())"),{'id':'a'*32})
        db.session.execute(sa.text("INSERT INTO show_recordings(id,session_id,station_id,storage_key,status,duration_ms,file_size_bytes) VALUES(:id,:show,1,:key,'complete',5000,12345)"),{'id':'b'*32,'show':'a'*32,'key':'b'*32+'.mp3'})
        db.session.commit()
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    from app.models import ShowRecording
    with app.app_context():
        row=ShowRecording.query.one()
        assert row.name=='' and row.revision==0 and row.deleted_at is None
        assert row.duration_ms==5000 and row.file_size_bytes==12345 and row.session.dj_name=='Original DJ'
        row.name='Named show.mp3';db.session.commit()
    result=runner.invoke(args=['db','downgrade','f306a1b2c3d4']);assert result.exit_code==0,result.output
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    with app.app_context():
        row=ShowRecording.query.one()
        assert row.name=='' and row.storage_key=='b'*32+'.mp3' and row.duration_ms==5000


def test_concurrent_recording_renames_reject_stale_writer(pg_app):
    from app.models import ShowRecording
    from tests.test_web import admin_client
    with pg_app.app_context():
        station=Station.query.one();user=AdminUser.query.one()
        show=LiveSession(station_id=station.id,admin_user_id=user.id,dj_name='Concurrency')
        row=ShowRecording(session=show,station_id=station.id,admin_user_id=user.id,
                          storage_key='d'*32+'.mp3',status='complete',duration_ms=1000)
        db.session.add(row);db.session.commit();identifier=row.id
    clients=[admin_client(pg_app),admin_client(pg_app)];barrier=Barrier(2)
    def rename(index):
        barrier.wait(timeout=10)
        return clients[index].post(f'/admin/stations/test-station/recordings/{identifier}/rename',
            data={'csrf':'test-admin-csrf-token','revision':'0','name':f'Writer {index}'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(rename,range(2)))
    assert sorted(results)==[303,409]
    with pg_app.app_context():assert ShowRecording.query.one().revision==1
