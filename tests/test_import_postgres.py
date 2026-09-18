"""Real concurrent requests exercise PostgreSQL row locks and catalog races."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid
import pytest
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import Station, AdminUser, MusicImportItem, MusicImportSession, Artist
from tests.test_web import admin_client
from tests.test_import_sessions import post, BASE


@pytest.fixture
def pg_app(monkeypatch,tmp_path):
    url=os.getenv('FREO_TEST_POSTGRES_URL')
    if not url:pytest.skip('Use scripts/test-import-postgres.sh')
    schema='import_test_'+uuid.uuid4().hex
    engine=sa.create_engine(url)
    with engine.begin() as c:c.execute(sa.text(f'CREATE SCHEMA {schema}'))
    monkeypatch.setenv('DATABASE_URL',str(sa.engine.make_url(url).update_query_dict({'options':f'-csearch_path={schema}'})))
    monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing')
    with app.app_context():
        db.create_all();db.session.add(Station(name='Test',slug='test-station'));db.session.add(AdminUser(email='admin@example.test',password_hash='unused'));db.session.commit()
    root=tmp_path/'uploads';root.mkdir();app.config['FREO_UPLOAD_ROOT']=str(root)
    yield app
    with app.app_context():db.session.remove();db.engine.dispose()
    with engine.begin() as c:c.execute(sa.text(f'DROP SCHEMA {schema} CASCADE'))
    engine.dispose()


def race(function):
    gate=threading.Barrier(2)
    def call(index):gate.wait(timeout=5);return function(index)
    with ThreadPoolExecutor(2) as pool:return list(pool.map(call,range(2)))


def test_concurrent_artist_creation_reuses_canonical_identity(pg_app):
    results=race(lambda index:post(admin_client(pg_app),BASE.replace('/imports','/catalog/artists'),name='Amber State' if index else ' AMBER   STATE '))
    assert [r.status_code for r in results]==[200,200]
    assert results[0].json['id']==results[1].json['id']
    assert results[0].json['name']==results[1].json['name']
    with pg_app.app_context():assert Artist.query.count()==1


def test_concurrent_draft_edit_rejects_stale_revision(pg_app):
    session=post(admin_client(pg_app),BASE).json;identifier=str(uuid.uuid4())
    with pg_app.app_context():
        db.session.add(MusicImportItem(id=identifier,session_id=session['id'],original_filename='song.mp3',relative_path='',size_bytes=1,checksum='a'*64,status='ready'))
        db.session.commit()
    results=race(lambda index:post(admin_client(pg_app),session['url']+'/items/'+identifier,{'revision':1,'choices':{'title':f'Choice {index}'}}))
    assert sorted(r.status_code for r in results)==[200,409]
    with pg_app.app_context():assert db.session.get(MusicImportItem,identifier).revision==2


def test_concurrent_finalize_is_idempotent(pg_app):
    session=post(admin_client(pg_app),BASE).json;identifier=str(uuid.uuid4())
    with pg_app.app_context():
        db.session.add(MusicImportItem(id=identifier,session_id=session['id'],original_filename='song.mp3',relative_path='',size_bytes=1,checksum='b'*64,status='ready'))
        db.session.commit()
    results=race(lambda index:post(admin_client(pg_app),session['url'],{'action':'finalize','items':[{'id':identifier,'revision':1}]}))
    assert [r.status_code for r in results]==[200,200]
    with pg_app.app_context():
        from app.models import MediaIngestJob
        assert MediaIngestJob.query.count()==1


def test_concurrent_album_save_and_single_edit_preserve_revision(pg_app):
    client=admin_client(pg_app);session=post(client,BASE).json;identifier=str(uuid.uuid4())
    with pg_app.app_context():
        db.session.add(MusicImportItem(id=identifier,session_id=session['id'],original_filename='song.mp3',
            relative_path='',size_bytes=1,checksum='c'*64,status='ready'))
        db.session.commit()
    def edit(index):
        if index:
            return post(admin_client(pg_app),session['url'],{'action':'save-items','items':[
                {'id':identifier,'revision':1,'choices':{'title':'Album edit'}}]})
        return post(admin_client(pg_app),session['url']+'/items/'+identifier,
            {'revision':1,'choices':{'title':'Individual edit'}})
    results=race(edit)
    assert sorted(response.status_code for response in results)==[200,409]
    with pg_app.app_context():assert db.session.get(MusicImportItem,identifier).revision==2
