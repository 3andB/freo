"""Campaign display policy and assets; retain legacy configuration and audio traffic."""
from datetime import date, datetime, timezone
import uuid
from alembic import op
import sqlalchemy as sa

revision = 'fb06a1b2c3d4'
down_revision = 'fa06a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('campaigns', sa.Column('advertising', sa.JSON(), nullable=True))
    op.create_table('campaign_display_assets',
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('device', sa.String(7), primary_key=True),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('version', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False), sa.Column('height', sa.Integer(), nullable=False),
        sa.CheckConstraint("device IN ('desktop','mobile')", name='ck_campaign_asset_device'))
    conn = op.get_bind(); meta = sa.MetaData()
    tables = {name: sa.Table(name, meta, autoload_with=conn) for name in
        ('advertisers', 'campaigns', 'station_player_settings', 'station_player_assets', 'campaign_display_assets')}
    now = datetime.now(timezone.utc)
    for row in conn.execute(sa.select(tables['station_player_settings'])).mappings():
        config = row['config'] or {}
        for placement in ('top', 'bottom'):
            prefix = 'ad_'+placement
            images = list(conn.execute(sa.select(tables['station_player_assets']).where(
                tables['station_player_assets'].c.station_id == row['station_id'],
                tables['station_player_assets'].c.kind.in_([prefix, prefix+'_mobile']))).mappings())
            if not images and not any(config.get(prefix+suffix) for suffix in ('_enabled','_url','_unit','_iframe','_start','_end','_alt')): continue
            name = 'Existing '+placement.title()+' advertising'; slug = 'legacy-ad-'+uuid.uuid4().hex
            advertiser = conn.execute(tables['advertisers'].insert().values(station_id=row['station_id'],
                name=name, slug=slug, enabled=True, notes='', created_at=now, updated_at=now)).inserted_primary_key[0]
            policy = dict(active=bool(config.get(prefix+'_enabled')), start=config.get(prefix+'_start',''),
                end=config.get(prefix+'_end',''), priority=100, weight=1, placement=placement, surfaces=['player'],
                source=config.get(prefix+'_source','image'), destination=config.get(prefix+'_url',''),
                label=config.get(prefix+'_alt',''), unit=config.get(prefix+'_unit',''), iframe=config.get(prefix+'_iframe',''),
                desktop_size=config.get(prefix+'_desktop_size','728x90'), mobile_size=config.get(prefix+'_mobile_size','320x50'))
            campaign = conn.execute(tables['campaigns'].insert().values(station_id=row['station_id'], advertiser_id=advertiser,
                name=name, slug=slug, status='DRAFT', enabled=True, start_date=date.today(), end_date=date(9999,12,31),
                priority=100, notes='', created_at=now, updated_at=now, advertising=policy)).inserted_primary_key[0]
            for image in images:
                import struct
                width, height = (image['width'], image['height']) if image['width'] and image['height'] else struct.unpack('>II', image['image'][16:24])
                conn.execute(tables['campaign_display_assets'].insert().values(campaign_id=campaign,
                    device='mobile' if image['kind'].endswith('_mobile') else 'desktop', image=image['image'],
                    version=image['version'], width=width, height=height))


def downgrade():
    # Legacy settings/images and campaign/traffic history remain untouched.
    op.drop_table('campaign_display_assets')
    op.drop_column('campaigns', 'advertising')
