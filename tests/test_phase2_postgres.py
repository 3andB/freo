"""Migration preservation and concurrent saves on disposable PostgreSQL."""
import os
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
import sqlalchemy as sa
from app import create_app, models as m
from app.extensions import db
from tests.test_schedule_postgres import pg_app
from tests.test_web import admin_client

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Disposable PostgreSQL required')


def test_migration_preserves_old_cues_and_defaults(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL']);monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    app=create_app('testing');runner=app.test_cli_runner()
    def migrate(*args):
        result=runner.invoke(args=['db',*args]);assert result.exit_code==0,result.output
    migrate('upgrade')
    with app.app_context():
        station=m.Station(name='Old station',slug='old',desired_state='stopped');db.session.add(station);db.session.flush()
        from tests.test_music_delete import add_song
        song=add_song(station);song.cue_in_ms=100;song.cue_out_ms=1800;song.notes='Keep notes'
        db.session.commit();identifier=song.id
    migrate('downgrade','f106a1b2c3d4')
    with app.app_context():
        before=dict(db.session.execute(sa.text('SELECT * FROM tracks WHERE id=:id'),{'id':identifier}).mappings().one())
    migrate('upgrade')
    with app.app_context():
        after=dict(db.session.execute(sa.text('SELECT * FROM tracks WHERE id=:id'),{'id':identifier}).mappings().one())
        assert all(after[k]==v for k,v in before.items())
        song=db.session.get(m.Track,identifier)
        assert not song.audio_edit_enabled and song.audio_edit_revision==0
        assert song.fade_in_ms==song.fade_out_ms==0 and song.gain_trim_db is None
        assert song.playback_duration_ms==2000
    migrate('downgrade','f106a1b2c3d4');migrate('upgrade')
    with app.app_context():
        assert db.session.get(m.Track,identifier).notes=='Keep notes'
    with app.app_context():
        db.session.remove();db.drop_all()
        db.session.execute(sa.text('DROP TABLE IF EXISTS alembic_version'));db.session.commit()


def test_concurrent_audio_saves_have_one_winner(pg_app):
    with pg_app.app_context():url='/admin/api/stations/test-station/song/'+m.Track.query.one().uuid+'/audio'
    clients=[admin_client(pg_app),admin_client(pg_app)];barrier=Barrier(2)
    def write(n):
        barrier.wait(timeout=10)
        return clients[n].post(url,data={'csrf':'test-admin-csrf-token','data':json.dumps(dict(revision=0,cue_in_ms=100+n*100))}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(write,range(2)))
    assert sorted(statuses)==[200,409]
    with pg_app.app_context():
        song=m.Track.query.one();assert song.audio_edit_revision==1
        assert db.session.query(m.Track.playback_duration_ms).one()[0]==song.playback_duration_ms
