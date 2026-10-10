"""Concurrent schedule writes against a disposable PostgreSQL database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import pytest
from app import create_app
from app.extensions import db
from app.models import Station, StreamMount, AutomationState, Track, AdminUser, ScheduleComposition
from app.services import visual_schedule as vs
from tests.test_web import admin_client

pytestmark=pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'),reason='Requires disposable PostgreSQL; use scripts/test-scheduling-postgres.sh')


@pytest.fixture
def pg_app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing')
    with app.app_context():
        db.create_all()
        station=Station(name='Schedule concurrency',slug='test-station',description='Isolated test',desired_state='stopped')
        station.stream=StreamMount();station.automation=AutomationState(enabled=True)
        db.session.add(station);db.session.flush()
        db.session.add(AdminUser(email='admin@example.test',password_hash='unused',active=True))
        track=Track(station_id=station.id,uuid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',title='Test',artist='Test',original_filename='test.mp3',storage_key='b'*32+'.mp3',media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='b'*64,enabled=True,ingest_status='accepted')
        db.session.add(track);db.session.flush();vs.policy(station,True);db.session.commit()
    yield app
    with app.app_context():
        db.session.remove();db.drop_all();db.engine.dispose()


def test_concurrent_documents_never_overwrite_each_other(pg_app):
    url='/admin/stations/test-station/schedule-studio/api/calendar'
    with pg_app.app_context():ref=dict(kind='song',id=Track.query.one().id)
    for iteration in range(10):
        with pg_app.app_context():revision=vs.policy(Station.query.one()).revision
        clients=[admin_client(pg_app),admin_client(pg_app)];barrier=Barrier(2)
        def write(index):
            payload=dict(revision=revision,items=[dict(id='entry',start=index*3600,end=(index+1)*3600,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))])
            barrier.wait(timeout=10)
            response=clients[index].post(url,data={'csrf':'test-admin-csrf-token','payload':json.dumps(payload)})
            return index,response.status_code,response.json
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,range(2)))
        assert sorted(r[1] for r in results)==[200,400],results
        winner=next(r[0] for r in results if r[1]==200)
        with pg_app.app_context():
            p=vs.policy(Station.query.one())
            assert p.revision==revision+1 and p.calendar[0]['start']==winner*3600


def test_block_transaction_rolls_back_under_postgres(pg_app):
    client=admin_client(pg_app)
    with pg_app.app_context():
        p=vs.policy(Station.query.one());revision=p.revision
        data=dict(revision=revision,composition=dict(kind='BLOCK',name='Rollback',sections=[]),items=[{}])
    result=client.post('/admin/stations/test-station/schedule-studio/api/block-workspace',data={'csrf':'test-admin-csrf-token','payload':json.dumps(data)})
    assert result.status_code==400
    with pg_app.app_context():
        assert ScheduleComposition.query.count()==0
        assert vs.policy(Station.query.one()).revision==revision


@pytest.mark.parametrize('same_item', [False, True])
def test_concurrent_autosaves_merge_only_independent_items(pg_app, same_item):
    with pg_app.app_context():
        row=vs.policy(Station.query.one());revision=row.revision
        ref=dict(kind='song',id=Track.query.one().id)
    clients=[admin_client(pg_app),admin_client(pg_app)];barrier=Barrier(2)
    def write(index):
        payload=dict(revision=revision,base=[],items=[dict(id='same' if same_item else str(index),start=index*3600,end=(index+1)*3600,source=ref,rule=dict(frequency='once',anchor='2026-09-21'))])
        barrier.wait(timeout=10)
        response=clients[index].post('/admin/stations/test-station/schedule-studio/api/calendar',data={'csrf':'test-admin-csrf-token','payload':json.dumps(payload)})
        return response.status_code,response.json
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,range(2)))
    assert sorted(r[0] for r in results)==([200,409] if same_item else [200,200]),results
    with pg_app.app_context():
        row=vs.policy(Station.query.one())
        assert len(row.calendar)==(1 if same_item else 2)
        assert row.revision==revision+(1 if same_item else 2)
