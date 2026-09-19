"""Full migration chain and classified playlist backfill on disposable PostgreSQL."""
import os
import pytest
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import Station, Playlist, Track, TimedEvent
from app.services.stations import create_station

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Requires isolated PostgreSQL')


def test_event_upgrade_preserves_custom_playlist_and_seeds_system_collections(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','ab28c910d642'])
    assert result.exit_code==0,result.output
    with app.app_context():
        station=Station(name='Existing',slug='existing',description='',desired_state='stopped',timezone='Pacific/Auckland')
        db.session.add(station);db.session.commit();identifier=station.id
        db.session.execute(sa.text("INSERT INTO playlists(station_id,name,description,mode,revision) VALUES(:station,'STATION','Custom playlist','RANDOM',1)"),dict(station=identifier));db.session.commit()
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    with app.app_context():
        playlists=Playlist.query.filter_by(station_id=identifier).order_by(Playlist.id).all()
        assert len(playlists)==3 and playlists[0].system_key is None and playlists[0].description=='Custom playlist'
        assert [p.system_key for p in playlists[1:]]==['STATION','COMMERCIALS']
        new=create_station('New','new')
        assert [p.name for p in Playlist.query.filter_by(station_id=new.id).order_by(Playlist.id)]==['Playlist 1','Playlist 2','STATION','COMMERCIALS']
        assert 'PLAYLIST' in str(sa.inspect(db.engine).get_check_constraints('timed_events'))
        db.session.remove();db.drop_all();db.session.execute(sa.text('DROP TABLE IF EXISTS alembic_version'));db.session.commit();db.engine.dispose()
