"""Phase 9 migration preserves existing media and output settings."""
import os
import pytest
from app import create_app
from app.extensions import db

pytestmark = pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'), reason='Disposable PostgreSQL required')


def test_upgrade_downgrade_preserves_existing_data(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing'); runner = app.test_cli_runner()
    result = runner.invoke(args=['db', 'upgrade', 'f806a1b2c3d4'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        from app.models import Station, StreamMount, AdminUser, DJStationAssignment
        station = Station(name='Existing', slug='existing'); db.session.add(station); db.session.flush()
        station.stream = StreamMount(bitrate=64)
        dj = AdminUser(username='DJ', email='dj@example.test', password_hash='unused', role='DJ')
        db.session.add(dj); db.session.flush()
        db.session.add(DJStationAssignment(station_id=station.id, admin_user_id=dj.id))
        db.session.commit(); station_id, user_id = station.id, dj.id
    result = runner.invoke(args=['db', 'upgrade'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        from app.models import DJStationProfile
        assert StreamMount.query.one().bitrate == 64
        db.session.add(DJStationProfile(user_id=user_id, station_id=station_id, bio='Public bio'))
        db.session.commit()
        assert DJStationProfile.query.count() == 1
        DJStationAssignment.query.filter_by(admin_user_id=user_id, station_id=station_id).delete()
        db.session.commit()
        assert DJStationProfile.query.count() == 0
        StreamMount.query.one().bitrate = 192; db.session.commit()
    result = runner.invoke(args=['db', 'downgrade', 'f806a1b2c3d4'])
    assert result.exit_code != 0
    with app.app_context():
        db.session.remove()
        assert StreamMount.query.one().bitrate == 192
        StreamMount.query.one().bitrate = 96; db.session.commit()
    for args in (['db','downgrade','f806a1b2c3d4'], ['db','upgrade']):
        result = runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        assert StreamMount.query.one().bitrate == 96
        assert Station.query.one().slug == 'existing'
