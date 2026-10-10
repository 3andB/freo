"""Full migration chain and Phase 10 round-trip on a disposable PostgreSQL DB."""
import os
from datetime import datetime,timedelta,timezone
import pytest
from app import create_app
from app.extensions import db
from app.models import Station, StreamMount, SelectionDecision
from app.services.broadcast_reports import summary,tracks
pytestmark=pytest.mark.skipif(not os.environ.get('FREO_TEST_POSTGRES_URL'),reason='Requires isolated PostgreSQL')


def test_fresh_and_baseline_upgrade(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    with app.app_context():
        station=Station(name='Existing',slug='existing',description='',desired_state='stopped')
        station.stream=StreamMount(bitrate=96,audio_processing=dict(agc=True),pending_audio=None)
        db.session.add(station);db.session.commit()
    for args in [('db','downgrade','f906a1b2c3d4'),('db','upgrade')]:
        result=runner.invoke(args=args);assert result.exit_code==0,result.output
    with app.app_context():
        station=Station.query.one();assert station.stream.bitrate==96 and station.stream.audio_processing['agc']
        db.session.add(SelectionDecision(station_id=station.id,status='started',started_at=datetime.now(timezone.utc)-timedelta(seconds=1),performance_snapshot=dict(title='Confirmed',artist='Artist',album='',isrc=None,track_uuid='retained')))
        db.session.commit()
        result=summary(station,{})
        assert result['total_performances']==1
        assert list(tracks(station,result['period']))[0]['title']=='Confirmed'
