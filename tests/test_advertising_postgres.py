"""Real migration preserves legacy display configuration and existing traffic."""
import os
import hashlib
from datetime import date, datetime, timezone
import pytest
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from tests.test_station_settings_flags import png

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Disposable PostgreSQL required')


def test_legacy_migration_and_existing_traffic(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','test-only')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','fa06a1b2c3d4']);assert result.exit_code==0,result.output
    with app.app_context():
        from app.models import Station,StationPlayerSettings,StationPlayerAsset,Advertiser
        station=Station(name='Migration',slug='migration');db.session.add(station);db.session.flush()
        legacy=dict(ad_top_enabled=True,ad_top_url='https://example.test',ad_top_source='image',
            ad_top_start='2026-10-01T00:00:00+00:00',ad_bottom_enabled=False,
            ad_bottom_source='google',ad_bottom_unit='/1234/bottom',merch_url='https://example.test/store')
        db.session.add(StationPlayerSettings(station_id=station.id,revision=7,config=legacy))
        image=png(728,90)
        db.session.add(StationPlayerAsset(station_id=station.id,kind='ad_top',image=image,
            width=728,height=90,version=hashlib.sha256(image).hexdigest()))
        advertiser=Advertiser(station_id=station.id,name='Existing',slug='existing');db.session.add(advertiser);db.session.flush()
        table=sa.Table('campaigns',sa.MetaData(),autoload_with=db.engine)
        existing=db.session.execute(table.insert().values(station_id=station.id,advertiser_id=advertiser.id,name='Traffic',slug='traffic',
            status='ACTIVE',start_date=date(2026,1,1),end_date=date(2027,1,1),priority=200,enabled=True,notes='Keep',created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc))).inserted_primary_key[0]
        db.session.commit()
    result=runner.invoke(args=['db','upgrade']);assert result.exit_code==0,result.output
    with app.app_context():
        from app.models import Campaign,CampaignDisplayAsset
        assert Campaign.query.count()==3
        assert db.session.get(Campaign,existing).advertising is None
        assert db.session.get(Campaign,existing).status=='ACTIVE'
        assert StationPlayerSettings.query.one().config==legacy and StationPlayerSettings.query.one().revision==7
        assert CampaignDisplayAsset.query.one().image==image
        policies=[c.advertising for c in Campaign.query.all() if c.advertising]
        assert all(p['surfaces']==['player'] for p in policies)
        assert next(p for p in policies if p['placement']=='bottom')['unit']=='/1234/bottom'
    result=runner.invoke(args=['db','check']);assert result.exit_code==0,result.output
