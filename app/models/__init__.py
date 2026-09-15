from datetime import datetime, timezone

from app.extensions import db


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AuditEvent(db.Model):
    __tablename__ = 'audit_events'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'), index=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='SET NULL'), index=True)
    action = db.Column(db.String(48), nullable=False)
    target_type = db.Column(db.String(32), nullable=False)
    target_id = db.Column(db.String(64))
    summary = db.Column(db.String(240), nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    admin_user = db.relationship('AdminUser')
    station = db.relationship('Station')


class MediaIngestJob(db.Model):
    __tablename__ = 'media_ingest_jobs'
    __table_args__ = (db.CheckConstraint("status IN ('pending','processing','accepted','duplicate','rejected','error')", name='ck_media_ingest_job_status'),)
    id = db.Column(db.String(36), primary_key=True)
    kind = db.Column(db.String(12), nullable=False, default='ingest')
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    original_filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='pending', index=True)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='SET NULL'))
    imaging_type = db.Column(db.String(20))
    imaging_name = db.Column(db.String(200))
    cart_code = db.Column(db.String(32))
    error_code = db.Column(db.String(48))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))
    station = db.relationship('Station')
    admin_user = db.relationship('AdminUser')
    track = db.relationship('Track')
    imaging_asset = db.relationship('ImagingAsset')


class Station(db.Model):
    __tablename__ = 'stations'
    __table_args__ = (db.CheckConstraint("desired_state IN ('stopped','running')", name='ck_stations_desired_state'),)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False, unique=True, index=True)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    desired_state = db.Column(db.String(12), nullable=False, default='stopped')
    timezone = db.Column(db.String(64), nullable=False, default='UTC')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    stream = db.relationship('StreamMount', back_populates='station', uselist=False, cascade='all, delete-orphan')


class StreamMount(db.Model):
    __tablename__ = 'stream_mounts'
    __table_args__ = (
        db.CheckConstraint("format = 'mp3'", name='ck_stream_mounts_format'),
        db.CheckConstraint('bitrate = 64', name='ck_stream_mounts_bitrate'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, unique=True)
    format = db.Column(db.String(12), nullable=False, default='mp3')
    bitrate = db.Column(db.Integer, nullable=False, default=64)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', back_populates='stream')

    @property
    def mount(self):
        return '/' + self.station.slug

    @property
    def public_path(self):
        return '/stream/' + self.station.slug


class Artist(db.Model):
    __tablename__ = 'artists'
    __table_args__ = (db.UniqueConstraint('station_id', 'normalized_name', name='uq_artist_station_name'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station')


class Album(db.Model):
    __tablename__ = 'albums'
    __table_args__ = (db.UniqueConstraint('station_id', 'artist_id', 'normalized_title', name='uq_album_station_artist_title'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    artist_id = db.Column(db.Integer, db.ForeignKey('artists.id', ondelete='RESTRICT'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    normalized_title = db.Column(db.String(200), nullable=False)
    album_artist = db.Column(db.String(200), nullable=False, default='')
    release_year = db.Column(db.Integer)
    genre = db.Column(db.String(100), nullable=False, default='')
    artwork_key = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station')
    artist = db.relationship('Artist', backref='albums')


song_tags = db.Table(
    'song_tags',
    db.Column('track_id', db.Integer, db.ForeignKey('tracks.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('music_tags.id', ondelete='CASCADE'), primary_key=True),
)


class MusicTag(db.Model):
    __tablename__ = 'music_tags'
    __table_args__ = (db.UniqueConstraint('station_id', 'slug', name='uq_music_tag_station_slug'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(80), nullable=False)


class Track(db.Model):
    __tablename__ = 'tracks'
    __table_args__ = (
        db.UniqueConstraint('station_id', 'checksum_sha256', name='uq_tracks_station_checksum'),
        db.CheckConstraint("ingest_status IN ('accepted','rejected')", name='ck_tracks_ingest_status'),
        db.CheckConstraint('duration_ms > 0', name='ck_tracks_duration'),
        db.CheckConstraint('file_size_bytes > 0', name='ck_tracks_size'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False, index=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    album = db.Column(db.String(200), nullable=False, default='')
    artist_id = db.Column(db.Integer, db.ForeignKey('artists.id', ondelete='RESTRICT'), index=True)
    album_id = db.Column(db.Integer, db.ForeignKey('albums.id', ondelete='SET NULL'), index=True)
    album_artist = db.Column(db.String(200), nullable=False, default='')
    track_number = db.Column(db.Integer)
    disc_number = db.Column(db.Integer)
    release_year = db.Column(db.Integer)
    genre = db.Column(db.String(100), nullable=False, default='')
    isrc = db.Column(db.String(20), nullable=False, default='')
    artwork_key = db.Column(db.String(50))
    bpm = db.Column(db.Float)
    loudness_lufs = db.Column(db.Float)
    true_peak_db = db.Column(db.Float)
    cue_in_ms = db.Column(db.Integer)
    cue_out_ms = db.Column(db.Integer)
    segue_ms = db.Column(db.Integer)
    analysis_status = db.Column(db.String(16), nullable=False, default='pending')
    scheduling_restrictions = db.Column(db.JSON, nullable=False, default=dict)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(50), nullable=False)
    media_type = db.Column(db.String(12), nullable=False)
    duration_ms = db.Column(db.Integer, nullable=False)
    bitrate_kbps = db.Column(db.Integer)
    sample_rate_hz = db.Column(db.Integer, nullable=False)
    channels = db.Column(db.Integer, nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    ingest_status = db.Column(db.String(12), nullable=False, default='accepted')
    decommissioned_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref=db.backref('tracks', lazy='dynamic'))
    catalog_artist = db.relationship('Artist', backref='songs')
    catalog_album = db.relationship('Album', backref='songs')
    tags = db.relationship('MusicTag', secondary=song_tags, backref='songs')


track_categories = db.Table(
    'track_categories',
    db.Column('track_id', db.Integer, db.ForeignKey('tracks.id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('media_categories.id', ondelete='CASCADE'), primary_key=True),
)


imaging_group_assets = db.Table(
    'imaging_group_assets',
    db.Column('asset_id', db.Integer, db.ForeignKey('imaging_assets.id', ondelete='CASCADE'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('imaging_groups.id', ondelete='CASCADE'), primary_key=True),
)


IMAGING_TYPES = ('CART', 'STATION_ID', 'SWEEPER', 'LINER', 'PROMO', 'JINGLE', 'COMMERCIAL', 'GENERIC')


class ImagingAsset(db.Model):
    __tablename__ = 'imaging_assets'
    __table_args__ = (
        db.UniqueConstraint('uuid', name='imaging_assets_uuid_key'),
        db.UniqueConstraint('station_id', 'checksum_sha256', name='uq_imaging_station_checksum'),
        db.UniqueConstraint('station_id', 'cart_code', name='uq_imaging_station_cart_code'),
        db.CheckConstraint("asset_type IN ('CART','STATION_ID','SWEEPER','LINER','PROMO','JINGLE','COMMERCIAL','GENERIC')", name='ck_imaging_asset_type'),
        db.CheckConstraint("ingest_status IN ('accepted','rejected')", name='ck_imaging_ingest_status'),
        db.CheckConstraint('duration_ms > 0 AND file_size_bytes > 0', name='ck_imaging_positive_size'),
    )
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    cart_code = db.Column(db.String(32))
    asset_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(50), nullable=False)
    media_type = db.Column(db.String(12), nullable=False)
    duration_ms = db.Column(db.Integer, nullable=False)
    bitrate_kbps = db.Column(db.Integer)
    sample_rate_hz = db.Column(db.Integer, nullable=False)
    channels = db.Column(db.Integer, nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    ingest_status = db.Column(db.String(12), nullable=False, default='accepted')
    decommissioned_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='imaging_assets')
    groups = db.relationship('ImagingGroup', secondary=imaging_group_assets, back_populates='assets')


class ImagingGroup(db.Model):
    __tablename__ = 'imaging_groups'
    __table_args__ = (
        db.UniqueConstraint('station_id', 'slug', name='uq_imaging_group_station_slug'),
        db.CheckConstraint('minimum_separation_seconds BETWEEN 0 AND 86400', name='ck_imaging_group_separation'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    minimum_separation_seconds = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='imaging_groups')
    assets = db.relationship('ImagingAsset', secondary=imaging_group_assets, back_populates='groups')


class MediaCategory(db.Model):
    __tablename__ = 'media_categories'
    __table_args__ = (db.UniqueConstraint('station_id', 'slug', name='uq_category_station_slug'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='categories')
    tracks = db.relationship('Track', secondary=track_categories, backref='categories')


class Rotation(db.Model):
    __tablename__ = 'rotations'
    __table_args__ = (db.UniqueConstraint('station_id', 'slug', name='uq_rotation_station_slug'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='rotations')
    slots = db.relationship('RotationSlot', back_populates='rotation', order_by='RotationSlot.position', cascade='all, delete-orphan')


class RotationSlot(db.Model):
    __tablename__ = 'rotation_slots'
    __table_args__ = (db.UniqueConstraint('rotation_id', 'position', name='uq_rotation_slot_position'),)
    id = db.Column(db.Integer, primary_key=True)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='CASCADE'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='RESTRICT'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    rotation = db.relationship('Rotation', back_populates='slots')
    category = db.relationship('MediaCategory')


class AutomationState(db.Model):
    __tablename__ = 'automation_states'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    active_rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='SET NULL'))
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    hold = db.Column(db.Boolean, nullable=False, default=False)
    operator_mode = db.Column(db.String(16), nullable=False, default='AUTO')
    next_slot_index = db.Column(db.Integer, nullable=False, default=0)
    track_separation_seconds = db.Column(db.Integer, nullable=False, default=0)
    artist_separation_seconds = db.Column(db.Integer, nullable=False, default=0)
    worker_heartbeat_at = db.Column(db.DateTime(timezone=True))
    observed_queue_depth = db.Column(db.Integer)
    default_clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='SET NULL'))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref=db.backref('automation', uselist=False))
    active_rotation = db.relationship('Rotation')
    default_clock = db.relationship('Clock', foreign_keys=[default_clock_id])


class Clock(db.Model):
    __tablename__ = 'clocks'
    __table_args__ = (db.UniqueConstraint('station_id', 'slug', name='uq_clock_station_slug'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='clocks')
    slots = db.relationship('ClockSlot', back_populates='clock', order_by='ClockSlot.position', cascade='all, delete-orphan')


class EventBlock(db.Model):
    __tablename__ = 'event_blocks'
    __table_args__ = (db.UniqueConstraint('station_id', 'slug', name='uq_event_block_station_slug'),
        db.CheckConstraint("block_type IN ('GENERIC','STOPSET','NEWS','LEGAL_ID','PROMO_BLOCK','SPECIAL')", name='ck_event_block_type'),
        db.CheckConstraint("failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')", name='ck_event_block_failure_policy'))
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False); slug = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    block_type = db.Column(db.String(20), nullable=False, default='GENERIC')
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    failure_policy = db.Column(db.String(20), nullable=False, default='ABORT_BLOCK')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='event_blocks')
    items = db.relationship('EventBlockItem', back_populates='block', order_by='EventBlockItem.position', cascade='all, delete-orphan')
    @property
    def duration_ms(self):
        return sum((i.track or i.imaging_asset).duration_ms for i in self.items if i.enabled and (i.track or i.imaging_asset))


class EventBlockItem(db.Model):
    __tablename__ = 'event_block_items'
    __table_args__ = (db.UniqueConstraint('event_block_id', 'position', name='uq_event_block_item_position'),
        db.CheckConstraint('position > 0', name='ck_event_block_item_position'),
        db.CheckConstraint("item_type IN ('TRACK','IMAGING_ASSET')", name='ck_event_block_item_type'),
        db.CheckConstraint("failure_policy IS NULL OR failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')", name='ck_event_block_item_failure_policy'),
        db.CheckConstraint("(item_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL)", name='ck_event_block_item_target'))
    id = db.Column(db.Integer, primary_key=True)
    event_block_id = db.Column(db.Integer, db.ForeignKey('event_blocks.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False); item_type = db.Column(db.String(20), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='RESTRICT'))
    enabled = db.Column(db.Boolean, nullable=False, default=True); label = db.Column(db.String(120)); failure_policy = db.Column(db.String(20))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    block = db.relationship('EventBlock', back_populates='items'); track = db.relationship('Track'); imaging_asset = db.relationship('ImagingAsset')


class Advertiser(db.Model):
    __tablename__='advertisers'; __table_args__=(db.UniqueConstraint('station_id','slug',name='uq_advertiser_station_slug'),)
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True)
    name=db.Column(db.String(120),nullable=False); slug=db.Column(db.String(64),nullable=False); external_reference=db.Column(db.String(80)); contact_name=db.Column(db.String(120)); contact_email=db.Column(db.String(254)); contact_phone=db.Column(db.String(40)); notes=db.Column(db.String(1000),nullable=False,default=''); enabled=db.Column(db.Boolean,nullable=False,default=True)
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); station=db.relationship('Station',backref='advertisers')

class Campaign(db.Model):
    __tablename__='campaigns'; __table_args__=(db.UniqueConstraint('station_id','slug',name='uq_campaign_station_slug'),db.CheckConstraint("status IN ('DRAFT','ACTIVE','PAUSED','COMPLETED','CANCELLED')",name='ck_campaign_status'),db.CheckConstraint('start_date <= end_date',name='ck_campaign_dates'))
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); advertiser_id=db.Column(db.Integer,db.ForeignKey('advertisers.id',ondelete='RESTRICT'),nullable=False)
    name=db.Column(db.String(120),nullable=False); slug=db.Column(db.String(64),nullable=False); status=db.Column(db.String(12),nullable=False,default='DRAFT'); start_date=db.Column(db.Date,nullable=False); end_date=db.Column(db.Date,nullable=False); priority=db.Column(db.Integer,nullable=False,default=100); target_spot_count=db.Column(db.Integer); enabled=db.Column(db.Boolean,nullable=False,default=True); notes=db.Column(db.String(1000),nullable=False,default='')
    created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); station=db.relationship('Station'); advertiser=db.relationship('Advertiser',backref='campaigns')

class CommercialCreative(db.Model):
    __tablename__='commercial_creatives'; __table_args__=(db.UniqueConstraint('station_id','creative_code',name='uq_creative_station_code'),)
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); campaign_id=db.Column(db.Integer,db.ForeignKey('campaigns.id',ondelete='RESTRICT'),nullable=False); imaging_asset_id=db.Column(db.Integer,db.ForeignKey('imaging_assets.id',ondelete='RESTRICT'),nullable=False)
    name=db.Column(db.String(120),nullable=False); creative_code=db.Column(db.String(40),nullable=False); enabled=db.Column(db.Boolean,nullable=False,default=True); start_date=db.Column(db.Date); end_date=db.Column(db.Date); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); campaign=db.relationship('Campaign',backref='creatives'); imaging_asset=db.relationship('ImagingAsset')

class CampaignScheduleRule(db.Model):
    __tablename__='campaign_schedule_rules'; __table_args__=(db.CheckConstraint('target_spots_per_day > 0',name='ck_rule_target_positive'),db.CheckConstraint('start_time < end_time',name='ck_rule_daypart'))
    id=db.Column(db.Integer,primary_key=True); campaign_id=db.Column(db.Integer,db.ForeignKey('campaigns.id',ondelete='CASCADE'),nullable=False); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); weekdays=db.Column(db.String(20),nullable=False); start_time=db.Column(db.Time,nullable=False); end_time=db.Column(db.Time,nullable=False); target_spots_per_day=db.Column(db.Integer,nullable=False); minimum_separation_seconds=db.Column(db.Integer,nullable=False,default=0); maximum_spots_per_day=db.Column(db.Integer); priority=db.Column(db.Integer,nullable=False,default=100); enabled=db.Column(db.Boolean,nullable=False,default=True); campaign=db.relationship('Campaign',backref='rules')

class TrafficStopset(db.Model):
    __tablename__='traffic_stopsets'; __table_args__=(db.UniqueConstraint('station_id','slug',name='uq_traffic_stopset_station_slug'),db.CheckConstraint("timing_mode IN ('SOFT','HARD','NON_INTERRUPTING')",name='ck_traffic_stopset_mode'))
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); name=db.Column(db.String(120),nullable=False); slug=db.Column(db.String(64),nullable=False); weekdays=db.Column(db.String(20),nullable=False); local_time=db.Column(db.Time,nullable=False); capacity_seconds=db.Column(db.Integer,nullable=False); max_spots=db.Column(db.Integer); timing_mode=db.Column(db.String(20),nullable=False,default='SOFT'); enabled=db.Column(db.Boolean,nullable=False,default=True); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); station=db.relationship('Station'); template_items=db.relationship('TrafficStopsetItem',back_populates='stopset',order_by='TrafficStopsetItem.position',cascade='all,delete-orphan')

class TrafficStopsetItem(db.Model):
    __tablename__='traffic_stopset_items'; __table_args__=(db.UniqueConstraint('traffic_stopset_id','position',name='uq_stopset_item_position'),db.CheckConstraint("(item_type='FIXED_IMAGING' AND imaging_asset_id IS NOT NULL) OR (item_type='COMMERCIAL_SLOT' AND imaging_asset_id IS NULL)",name='ck_stopset_item_target'))
    id=db.Column(db.Integer,primary_key=True); traffic_stopset_id=db.Column(db.Integer,db.ForeignKey('traffic_stopsets.id',ondelete='CASCADE'),nullable=False); position=db.Column(db.Integer,nullable=False); item_type=db.Column(db.String(20),nullable=False); imaging_asset_id=db.Column(db.Integer,db.ForeignKey('imaging_assets.id',ondelete='RESTRICT')); stopset=db.relationship('TrafficStopset',back_populates='template_items'); imaging_asset=db.relationship('ImagingAsset')

class TrafficLog(db.Model):
    __tablename__='traffic_logs'; __table_args__=(db.UniqueConstraint('station_id','log_date',name='uq_traffic_log_date'),db.CheckConstraint("status IN ('DRAFT','GENERATED','FINALIZED','RECONCILED')",name='ck_traffic_log_status'))
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); log_date=db.Column(db.Date,nullable=False); status=db.Column(db.String(12),nullable=False,default='DRAFT'); generated_at=db.Column(db.DateTime(timezone=True)); finalized_at=db.Column(db.DateTime(timezone=True)); reconciled_at=db.Column(db.DateTime(timezone=True)); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); station=db.relationship('Station'); placements=db.relationship('TrafficPlacement',back_populates='traffic_log',cascade='all,delete-orphan')

class TrafficPlacement(db.Model):
    __tablename__='traffic_placements'; __table_args__=(db.UniqueConstraint('traffic_log_id','traffic_stopset_id','position',name='uq_traffic_placement_position'),db.CheckConstraint("status IN ('PLANNED','MATERIALIZED','QUEUED','AIRED','MISSED','FAILED','CANCELLED')",name='ck_traffic_placement_status'))
    id=db.Column(db.Integer,primary_key=True); traffic_log_id=db.Column(db.Integer,db.ForeignKey('traffic_logs.id',ondelete='CASCADE'),nullable=False); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); traffic_stopset_id=db.Column(db.Integer,db.ForeignKey('traffic_stopsets.id',ondelete='RESTRICT'),nullable=False); scheduled_for_utc=db.Column(db.DateTime(timezone=True),nullable=False); campaign_id=db.Column(db.Integer,db.ForeignKey('campaigns.id',ondelete='RESTRICT'),nullable=False); commercial_creative_id=db.Column(db.Integer,db.ForeignKey('commercial_creatives.id',ondelete='RESTRICT'),nullable=False); position=db.Column(db.Integer,nullable=False); status=db.Column(db.String(12),nullable=False,default='PLANNED'); is_makegood=db.Column(db.Boolean,nullable=False,default=False); makegood_for_id=db.Column(db.Integer,db.ForeignKey('traffic_placements.id',ondelete='RESTRICT')); event_block_execution_id=db.Column(db.Integer,db.ForeignKey('event_block_executions.id',ondelete='SET NULL')); event_block_item_id=db.Column(db.Integer,db.ForeignKey('event_block_items.id',ondelete='SET NULL')); event_block_item_execution_id=db.Column(db.Integer,db.ForeignKey('event_block_item_executions.id',ondelete='SET NULL')); confirmed_started_at=db.Column(db.DateTime(timezone=True)); failure_reason=db.Column(db.String(80)); advertiser_name=db.Column(db.String(120),nullable=False); campaign_name=db.Column(db.String(120),nullable=False); creative_name=db.Column(db.String(120),nullable=False); creative_code=db.Column(db.String(40),nullable=False); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); traffic_log=db.relationship('TrafficLog',back_populates='placements'); stopset=db.relationship('TrafficStopset'); campaign=db.relationship('Campaign'); creative=db.relationship('CommercialCreative'); makegood_for=db.relationship('TrafficPlacement',remote_side=[id])


class ClockSlot(db.Model):
    __tablename__ = 'clock_slots'
    __table_args__ = (
        db.UniqueConstraint('clock_id', 'position', name='uq_clock_slot_position'),
        db.CheckConstraint('position > 0', name='ck_clock_slot_position'),
        db.CheckConstraint("(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'EVENT_BLOCK' AND event_block_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL)", name='ck_clock_slot_target'),
    )
    id = db.Column(db.Integer, primary_key=True)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    slot_type = db.Column(db.String(20), nullable=False)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='RESTRICT'))
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='RESTRICT'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='RESTRICT'))
    imaging_group_id = db.Column(db.Integer, db.ForeignKey('imaging_groups.id', ondelete='RESTRICT'))
    event_block_id = db.Column(db.Integer, db.ForeignKey('event_blocks.id', ondelete='RESTRICT'))
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    label = db.Column(db.String(120))
    clock = db.relationship('Clock', back_populates='slots')
    rotation = db.relationship('Rotation')
    category = db.relationship('MediaCategory')
    imaging_asset = db.relationship('ImagingAsset')
    imaging_group = db.relationship('ImagingGroup')
    event_block = db.relationship('EventBlock')


class ScheduleAssignment(db.Model):
    __tablename__ = 'schedule_assignments'
    __table_args__ = (
        db.UniqueConstraint('station_id', 'weekday', 'start_time', name='uq_schedule_station_day_time'),
        db.CheckConstraint('weekday BETWEEN 0 AND 6', name='ck_schedule_weekday'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='RESTRICT'), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref='schedule_assignments')
    clock = db.relationship('Clock')


class ClockState(db.Model):
    __tablename__ = 'clock_states'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='SET NULL'))
    occurrence_key = db.Column(db.String(120))
    next_slot_index = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class RotationCursor(db.Model):
    __tablename__ = 'rotation_cursors'
    __table_args__ = (db.UniqueConstraint('station_id', 'rotation_id', name='uq_rotation_cursor_station_rotation'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='CASCADE'), nullable=False)
    next_slot_index = db.Column(db.Integer, nullable=False, default=0)


class SelectionDecision(db.Model):
    __tablename__ = 'selection_decisions'
    __table_args__ = (
        db.CheckConstraint("status IN ('selected','submitting','queued','started','failed')", name='ck_decision_status'),
        db.CheckConstraint('track_id IS NULL OR imaging_asset_id IS NULL', name='ck_decision_one_playable'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='SET NULL'))
    slot_id = db.Column(db.Integer, db.ForeignKey('rotation_slots.id', ondelete='SET NULL'))
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='SET NULL'))
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='SET NULL'))
    imaging_group_id = db.Column(db.Integer, db.ForeignKey('imaging_groups.id', ondelete='SET NULL'))
    selection_method = db.Column(db.String(24), nullable=False, default='music')
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    idempotency_key = db.Column(db.String(36), unique=True)
    selected_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(12), nullable=False, default='selected')
    candidate_count = db.Column(db.Integer, nullable=False, default=0)
    relaxation = db.Column(db.String(24), nullable=False, default='none')
    reason = db.Column(db.String(120), nullable=False, default='')
    liquidsoap_request_id = db.Column(db.Integer)
    socket_identity = db.Column(db.String(64))
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='SET NULL'))
    clock_slot_id = db.Column(db.Integer, db.ForeignKey('clock_slots.id', ondelete='SET NULL'))
    schedule_assignment_id = db.Column(db.Integer, db.ForeignKey('schedule_assignments.id', ondelete='SET NULL'))
    schedule_occurrence = db.Column(db.String(120))
    station = db.relationship('Station')
    track = db.relationship('Track')
    imaging_asset = db.relationship('ImagingAsset')
    imaging_group = db.relationship('ImagingGroup')
    category = db.relationship('MediaCategory')
    slot = db.relationship('RotationSlot')
    clock = db.relationship('Clock')
    clock_slot = db.relationship('ClockSlot')
    schedule_assignment = db.relationship('ScheduleAssignment')
    operator = db.relationship('AdminUser')


class LiveControlCommand(db.Model):
    """Worker-mediated skip only; never a generic socket command table."""
    __tablename__ = 'live_control_commands'
    __table_args__ = (db.CheckConstraint("status IN ('pending','sent','failed')", name='ck_live_control_status'),db.CheckConstraint("action IN ('SKIP','TAKEOVER')",name='ck_live_control_action'))
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    idempotency_key = db.Column(db.String(36), nullable=False, unique=True)
    expected_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    target_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    action = db.Column(db.String(12), nullable=False, default='SKIP')
    status = db.Column(db.String(12), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime(timezone=True))
    error_code = db.Column(db.String(40))
    station = db.relationship('Station')
    operator = db.relationship('AdminUser')
    expected_decision = db.relationship('SelectionDecision',foreign_keys=[expected_decision_id])
    target_decision = db.relationship('SelectionDecision',foreign_keys=[target_decision_id])


class LiveCartSlot(db.Model):
    __tablename__='live_cart_slots'
    __table_args__=(db.UniqueConstraint('station_id','role','position',name='uq_live_cart_station_role_position'),db.CheckConstraint("role IN ('HOT','ID')",name='ck_live_cart_role'),db.CheckConstraint("(role='HOT' AND position BETWEEN 1 AND 8) OR (role='ID' AND position BETWEEN 1 AND 4)",name='ck_live_cart_position'))
    id=db.Column(db.Integer,primary_key=True);station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True);role=db.Column(db.String(4),nullable=False);position=db.Column(db.Integer,nullable=False);imaging_asset_id=db.Column(db.Integer,db.ForeignKey('imaging_assets.id',ondelete='SET NULL'));label=db.Column(db.String(40),nullable=False,default='');imaging_asset=db.relationship('ImagingAsset');station=db.relationship('Station')


class LiveQueueSnapshot(db.Model):
    """Worker-observed socket state, stripped of paths and raw metadata."""
    __tablename__ = 'live_queue_snapshots'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    current_decision_id = db.Column(db.Integer)
    queued_decision_ids = db.Column(db.JSON, nullable=False, default=list)
    unknown_count = db.Column(db.Integer, nullable=False, default=0)
    observed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    error_code = db.Column(db.String(40))


class TimedEvent(db.Model):
    __tablename__ = 'timed_events'
    __table_args__ = (
        db.UniqueConstraint('uuid', name='timed_events_uuid_key'),
        db.CheckConstraint("timing_mode IN ('SOFT','HARD','NON_INTERRUPTING')", name='ck_timed_event_mode'),
        db.CheckConstraint("recurrence_type IN ('ONE_TIME','WEEKLY')", name='ck_timed_event_recurrence'),
        db.CheckConstraint("content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK')", name='ck_timed_event_content_type'),
        db.CheckConstraint("missed_policy IN ('SKIP','PLAY_LATE')", name='ck_timed_event_missed'),
        db.CheckConstraint("interrupt_policy IN ('NEVER','MUSIC_ONLY')", name='ck_timed_event_interrupt'),
        db.CheckConstraint("(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL AND event_block_id IS NULL) OR (content_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL)", name='ck_timed_event_content'),
        db.CheckConstraint("(recurrence_type='ONE_TIME' AND scheduled_at_utc IS NOT NULL AND weekday IS NULL AND local_time IS NULL) OR (recurrence_type='WEEKLY' AND scheduled_at_utc IS NULL AND weekday BETWEEN 0 AND 6 AND local_time IS NOT NULL)", name='ck_timed_event_schedule'),
        db.CheckConstraint('early_tolerance_seconds BETWEEN 0 AND 3600 AND late_tolerance_seconds BETWEEN 1 AND 86400', name='ck_timed_event_window'),
    )
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    timing_mode = db.Column(db.String(20), nullable=False)
    content_type = db.Column(db.String(20), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='RESTRICT'))
    event_block_id = db.Column(db.Integer, db.ForeignKey('event_blocks.id', ondelete='RESTRICT'))
    recurrence_type = db.Column(db.String(12), nullable=False)
    scheduled_at_utc = db.Column(db.DateTime(timezone=True))
    weekday = db.Column(db.Integer)
    local_time = db.Column(db.Time)
    early_tolerance_seconds = db.Column(db.Integer, nullable=False, default=0)
    late_tolerance_seconds = db.Column(db.Integer, nullable=False, default=10)
    missed_policy = db.Column(db.String(12), nullable=False, default='SKIP')
    interrupt_policy = db.Column(db.String(16), nullable=False, default='NEVER')
    priority = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station')
    track = db.relationship('Track')
    imaging_asset = db.relationship('ImagingAsset')
    event_block = db.relationship('EventBlock')
    occurrences = db.relationship('TimedEventOccurrence', back_populates='event', cascade='all, delete-orphan')


class TimedEventOccurrence(db.Model):
    __tablename__ = 'timed_event_occurrences'
    __table_args__ = (
        db.UniqueConstraint('timed_event_id', 'scheduled_for_utc', name='uq_timed_occurrence_instant'),
        db.CheckConstraint("state IN ('PENDING','READY','QUEUED','STARTED','MISSED','FAILED','CANCELLED')", name='ck_timed_occurrence_state'),
    )
    id = db.Column(db.Integer, primary_key=True)
    timed_event_id = db.Column(db.Integer, db.ForeignKey('timed_events.id', ondelete='CASCADE'), nullable=False, index=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    scheduled_for_utc = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    eligible_at_utc = db.Column(db.DateTime(timezone=True), nullable=False)
    deadline_at_utc = db.Column(db.DateTime(timezone=True), nullable=False)
    state = db.Column(db.String(12), nullable=False, default='PENDING', index=True)
    selection_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'), unique=True)
    queued_at = db.Column(db.DateTime(timezone=True))
    started_at = db.Column(db.DateTime(timezone=True))
    missed_at = db.Column(db.DateTime(timezone=True))
    failure_reason = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    event = db.relationship('TimedEvent', back_populates='occurrences')
    station = db.relationship('Station')
    selection_decision = db.relationship('SelectionDecision', foreign_keys=[selection_decision_id],
        backref=db.backref('timed_event_occurrence', uselist=False))

    @property
    def timing_offset_seconds(self):
        if not self.started_at:
            return None
        started = self.started_at.replace(tzinfo=self.started_at.tzinfo or timezone.utc)
        scheduled = self.scheduled_for_utc.replace(tzinfo=self.scheduled_for_utc.tzinfo or timezone.utc)
        return (started - scheduled).total_seconds()


class EventBlockExecution(db.Model):
    __tablename__ = 'event_block_executions'
    __table_args__ = (db.CheckConstraint("state IN ('PENDING','QUEUED','STARTED','COMPLETED','ABORTED','FAILED','CANCELLED')", name='ck_block_execution_state'),
        db.CheckConstraint("source IN ('TIMED_EVENT','CLOCK','MANUAL')", name='ck_block_execution_source'))
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    event_block_id = db.Column(db.Integer, db.ForeignKey('event_blocks.id', ondelete='RESTRICT'), nullable=False)
    timed_event_occurrence_id = db.Column(db.Integer, db.ForeignKey('timed_event_occurrences.id', ondelete='SET NULL'), unique=True)
    clock_slot_id = db.Column(db.Integer, db.ForeignKey('clock_slots.id', ondelete='SET NULL'))
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    source = db.Column(db.String(16), nullable=False); state = db.Column(db.String(12), nullable=False, default='PENDING', index=True)
    started_at = db.Column(db.DateTime(timezone=True)); completed_at = db.Column(db.DateTime(timezone=True)); aborted_at = db.Column(db.DateTime(timezone=True))
    failure_reason = db.Column(db.String(80)); abort_requested = db.Column(db.Boolean, nullable=False, default=False); created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station'); block = db.relationship('EventBlock'); clock_slot = db.relationship('ClockSlot'); operator = db.relationship('AdminUser')
    timed_event_occurrence = db.relationship('TimedEventOccurrence', backref=db.backref('block_execution', uselist=False))
    items = db.relationship('EventBlockItemExecution', back_populates='execution', order_by='EventBlockItemExecution.position', cascade='all, delete-orphan')


class EventBlockItemExecution(db.Model):
    __tablename__ = 'event_block_item_executions'
    __table_args__ = (db.UniqueConstraint('block_execution_id', 'position', name='uq_block_item_execution_position'),
        db.CheckConstraint("state IN ('PENDING','QUEUED','STARTED','COMPLETED','SKIPPED','FAILED')", name='ck_block_item_execution_state'),
        db.CheckConstraint("item_type IN ('TRACK','IMAGING_ASSET')", name='ck_block_item_execution_type'),
        db.CheckConstraint("failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')", name='ck_block_item_execution_policy'),
        db.CheckConstraint("(item_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL)", name='ck_block_item_execution_target'))
    id = db.Column(db.Integer, primary_key=True)
    block_execution_id = db.Column(db.Integer, db.ForeignKey('event_block_executions.id', ondelete='CASCADE'), nullable=False, index=True)
    event_block_item_id = db.Column(db.Integer, db.ForeignKey('event_block_items.id', ondelete='SET NULL'))
    position = db.Column(db.Integer, nullable=False); item_type = db.Column(db.String(20), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT')); imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='RESTRICT'))
    label = db.Column(db.String(120)); failure_policy = db.Column(db.String(20), nullable=False); state = db.Column(db.String(12), nullable=False, default='PENDING')
    selection_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'), unique=True)
    queued_at = db.Column(db.DateTime(timezone=True)); started_at = db.Column(db.DateTime(timezone=True)); completed_at = db.Column(db.DateTime(timezone=True)); failed_at = db.Column(db.DateTime(timezone=True))
    failure_reason = db.Column(db.String(80)); created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)); updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    execution = db.relationship('EventBlockExecution', back_populates='items'); definition_item = db.relationship('EventBlockItem')
    track = db.relationship('Track'); imaging_asset = db.relationship('ImagingAsset')
    selection_decision = db.relationship('SelectionDecision', backref=db.backref('block_item_execution', uselist=False))


class AutomationHeartbeat(db.Model):
    __tablename__ = 'automation_heartbeat'
    id = db.Column(db.Integer, primary_key=True)
    seen_at = db.Column(db.DateTime(timezone=True), nullable=False)
