from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event, select, text, inspect
from app.services import copyright as copyright_ids
from app.extensions import db


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    import_notice_date = db.Column(db.Date)
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
    import_metadata = db.Column(db.JSON, nullable=False, default=dict, server_default='{}')
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
    freo_station_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    country = db.Column(db.String(2), nullable=False, default='', server_default='')
    genre = db.Column(db.String(100), nullable=False, default='', server_default='')
    directory_categories = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    directory_opt_in = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=False, unique=True, index=True)
    description = db.Column(db.String(500), nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    desired_state = db.Column(db.String(12), nullable=False, default='stopped')
    broadcast_revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    broadcast_status = db.Column(db.String(16), nullable=False, default='ready', server_default='ready')
    broadcast_error = db.Column(db.String(240), nullable=False, default='', server_default='')
    timezone = db.Column(db.String(64), nullable=False, default='UTC')
    target_lufs = db.Column(db.Float, nullable=False, default=-16.0)
    public_slug = db.Column(db.String(64), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = db.Column(db.DateTime(timezone=True), index=True)
    lifecycle_state = db.Column(db.String(24), nullable=False, default='ready', server_default='ready')
    lifecycle_error = db.Column(db.String(500), nullable=False, default='', server_default='')
    city = db.Column(db.String(120), nullable=False, default='', server_default='')
    region = db.Column(db.String(120), nullable=False, default='', server_default='')
    contact_email = db.Column(db.String(254), nullable=False, default='', server_default='')
    phone = db.Column(db.String(40), nullable=False, default='', server_default='')
    publish_contact = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    logo = db.relationship('StationLogo', uselist=False, cascade='all, delete-orphan')
    stream = db.relationship('StreamMount', back_populates='station', uselist=False, cascade='all, delete-orphan')


class StationDomain(db.Model):
    __tablename__ = 'station_domains'
    __table_args__ = (
        db.CheckConstraint('NOT enabled OR verified_at IS NOT NULL', name='ck_station_domains_verified'),
        db.CheckConstraint('NOT is_primary OR enabled', name='ck_station_domains_primary_enabled'),
        db.Index('uq_station_domains_primary', 'station_id', unique=True,
                 postgresql_where=db.text('is_primary'), sqlite_where=db.text('is_primary = 1')),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    hostname = db.Column(db.String(253), nullable=False, unique=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    verified_at = db.Column(db.DateTime(timezone=True))
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    verification_token = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref=db.backref('domains', cascade='all, delete-orphan', order_by='StationDomain.hostname'))

    @db.validates('hostname')
    def normalize_hostname(self, key, value):
        from app.services.station_domains import normalize_hostname
        return normalize_hostname(value, domain=True)


class StationAlias(db.Model):
    __tablename__ = 'station_aliases'
    slug = db.Column(db.String(64), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False)
    station = db.relationship('Station')


class StreamMount(db.Model):
    __tablename__ = 'stream_mounts'
    __table_args__ = (
        db.CheckConstraint("format = 'mp3'", name='ck_stream_mounts_format'),
        db.CheckConstraint('bitrate IN (64,96,128)', name='ck_stream_mounts_bitrate'),
        db.CheckConstraint("audio_status IN ('ready','pending','applying','failed')", name='ck_stream_mounts_audio_status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, unique=True)
    format = db.Column(db.String(12), nullable=False, default='mp3')
    bitrate = db.Column(db.Integer, nullable=False, default=64)
    audio_processing = db.Column(db.JSON, nullable=False, default=dict, server_default='{}')
    pending_audio = db.Column(db.JSON)
    audio_status = db.Column(db.String(12), nullable=False, default='ready', server_default='ready')
    audio_error = db.Column(db.String(240), nullable=False, default='', server_default='')
    audio_revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', back_populates='stream')

    @property
    def mount(self):
        return '/' + self.station.slug

    @property
    def public_path(self):
        return '/listen/' + self.station.public_slug if self.station.public_slug else '/stream/' + self.station.slug


class MusicArtwork(db.Model):
    __tablename__ = 'music_artwork'
    id = db.Column(db.String(36), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))


class Artist(db.Model):
    __tablename__ = 'artists'
    __table_args__ = (db.UniqueConstraint('station_id', 'normalized_name', name='uq_artist_station_name'),)
    available_to_all = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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
    available_to_all = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    artist_id = db.Column(db.Integer, db.ForeignKey('artists.id', ondelete='RESTRICT'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    normalized_title = db.Column(db.String(200), nullable=False)
    album_artist = db.Column(db.String(200), nullable=False, default='')
    release_year = db.Column(db.Integer)
    genre = db.Column(db.String(100), nullable=False, default='')
    artwork_key = db.Column(db.String(50))
    cover_id = db.Column(db.String(36), db.ForeignKey('music_artwork.id', ondelete='SET NULL'))
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
    color = db.Column(db.String(7), nullable=False, default='#b9e79b')
    description = db.Column(db.String(500), nullable=False, default='', server_default='')


class Track(db.Model):
    __mapper_args__ = {"batch": False}
    __tablename__ = 'tracks'
    __table_args__ = (
        db.UniqueConstraint('station_id', 'checksum_sha256', name='uq_tracks_station_checksum'),
        db.Index('ix_tracks_title_id', 'title', 'id'),
        db.UniqueConstraint('freo_track_id', name='uq_tracks_freo_track_id'),
        db.CheckConstraint("ingest_status IN ('accepted','rejected')", name='ck_tracks_ingest_status'),
        db.CheckConstraint("audio_kind IN ('MUSIC','STATION','COMMERCIALS')", name='ck_track_audio_kind'),
        db.CheckConstraint('duration_ms > 0', name='ck_tracks_duration'),
        db.CheckConstraint('file_size_bytes > 0', name='ck_tracks_size'),
    )
    audio_kind = db.Column(db.String(12), nullable=False, default='MUSIC', server_default='MUSIC', index=True)
    audio_subtype = db.Column(db.String(24), nullable=False, default='', server_default='')
    cart_code = db.Column(db.String(40))
    legacy_imaging_id = db.Column(db.Integer, unique=True)
    available_to_all = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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
    isrc = db.Column(db.String(20), nullable=True)
    freo_track_id = db.Column(db.String(12), nullable=False)
    artwork_key = db.Column(db.String(50))
    cover_id = db.Column(db.String(36), db.ForeignKey('music_artwork.id', ondelete='SET NULL'))
    bpm = db.Column(db.Float)
    loudness_lufs = db.Column(db.Float)
    true_peak_db = db.Column(db.Float)
    cue_in_ms = db.Column(db.Integer)
    cue_out_ms = db.Column(db.Integer)
    segue_ms = db.Column(db.Integer)
    waveform = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    preview_key = db.Column(db.String(50))
    auto_enable_pending = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    analysis_status = db.Column(db.String(16), nullable=False, default='pending')
    analysis_requested = db.Column(db.Boolean, nullable=False, default=False)
    analysis_attempts = db.Column(db.Integer, nullable=False, default=0)
    analysis_started_at = db.Column(db.DateTime(timezone=True))
    analyzed_at = db.Column(db.DateTime(timezone=True))
    analysis_retry_at = db.Column(db.DateTime(timezone=True))
    analysis_error = db.Column(db.String(240), nullable=False, default='')
    notes = db.Column(db.Text, nullable=False, default='')
    deleted_at = db.Column(db.DateTime(timezone=True))
    scheduling_restrictions = db.Column(db.JSON, nullable=False, default=dict)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(50), nullable=False)
    media_type = db.Column(db.String(12), nullable=False)
    duration_ms = db.Column(db.Integer, nullable=False)
    bitrate_kbps = db.Column(db.Integer)
    sample_rate_hz = db.Column(db.Integer, nullable=False)
    channels = db.Column(db.Integer, nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=True)
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
    crossfader = db.Column(db.Float, nullable=False, default=0.0)
    deck_a_playing = db.Column(db.Boolean, nullable=False, default=True)
    deck_b_playing = db.Column(db.Boolean, nullable=False, default=False)
    cued_track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
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
    cued_track = db.relationship('Track', foreign_keys=[cued_track_id])


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
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); campaign_id=db.Column(db.Integer,db.ForeignKey('campaigns.id',ondelete='RESTRICT'),nullable=False); imaging_asset_id=db.Column(db.Integer,db.ForeignKey('imaging_assets.id',ondelete='RESTRICT'),nullable=True)
    name=db.Column(db.String(120),nullable=False); creative_code=db.Column(db.String(40),nullable=False); enabled=db.Column(db.Boolean,nullable=False,default=True); start_date=db.Column(db.Date); end_date=db.Column(db.Date); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); campaign=db.relationship('Campaign',backref='creatives'); imaging_asset=db.relationship('ImagingAsset')

    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT'))
    track = db.relationship('Track')

    @property
    def audio(self):
        return self.track or self.imaging_asset

class CampaignScheduleRule(db.Model):
    __tablename__='campaign_schedule_rules'; __table_args__=(db.CheckConstraint('target_spots_per_day > 0',name='ck_rule_target_positive'),db.CheckConstraint('start_time < end_time',name='ck_rule_daypart'))
    id=db.Column(db.Integer,primary_key=True); campaign_id=db.Column(db.Integer,db.ForeignKey('campaigns.id',ondelete='CASCADE'),nullable=False); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); weekdays=db.Column(db.String(20),nullable=False); start_time=db.Column(db.Time,nullable=False); end_time=db.Column(db.Time,nullable=False); target_spots_per_day=db.Column(db.Integer,nullable=False); minimum_separation_seconds=db.Column(db.Integer,nullable=False,default=0); maximum_spots_per_day=db.Column(db.Integer); priority=db.Column(db.Integer,nullable=False,default=100); enabled=db.Column(db.Boolean,nullable=False,default=True); campaign=db.relationship('Campaign',backref='rules')

class TrafficStopset(db.Model):
    __tablename__='traffic_stopsets'; __table_args__=(db.UniqueConstraint('station_id','slug',name='uq_traffic_stopset_station_slug'),db.CheckConstraint("timing_mode IN ('SOFT','HARD','NON_INTERRUPTING')",name='ck_traffic_stopset_mode'))
    id=db.Column(db.Integer,primary_key=True); station_id=db.Column(db.Integer,db.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False,index=True); name=db.Column(db.String(120),nullable=False); slug=db.Column(db.String(64),nullable=False); weekdays=db.Column(db.String(20),nullable=False); local_time=db.Column(db.Time,nullable=False); capacity_seconds=db.Column(db.Integer,nullable=False); max_spots=db.Column(db.Integer); timing_mode=db.Column(db.String(20),nullable=False,default='SOFT'); enabled=db.Column(db.Boolean,nullable=False,default=True); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc)); updated_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); station=db.relationship('Station'); template_items=db.relationship('TrafficStopsetItem',back_populates='stopset',order_by='TrafficStopsetItem.position',cascade='all,delete-orphan')

class TrafficStopsetItem(db.Model):
    __tablename__='traffic_stopset_items'; __table_args__=(db.UniqueConstraint('traffic_stopset_id','position',name='uq_stopset_item_position'),db.CheckConstraint("(item_type='FIXED_IMAGING' AND imaging_asset_id IS NOT NULL AND track_id IS NULL) OR (item_type='FIXED_AUDIO' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='COMMERCIAL_SLOT' AND imaging_asset_id IS NULL AND track_id IS NULL)",name='ck_stopset_item_target'))
    id=db.Column(db.Integer,primary_key=True); traffic_stopset_id=db.Column(db.Integer,db.ForeignKey('traffic_stopsets.id',ondelete='CASCADE'),nullable=False); position=db.Column(db.Integer,nullable=False); item_type=db.Column(db.String(20),nullable=False); imaging_asset_id=db.Column(db.Integer,db.ForeignKey('imaging_assets.id',ondelete='RESTRICT')); stopset=db.relationship('TrafficStopset',back_populates='template_items'); imaging_asset=db.relationship('ImagingAsset')

    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT'))
    track = db.relationship('Track')

    @property
    def audio(self):
        return self.track or self.imaging_asset

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
        db.CheckConstraint("((slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR "
                           "(slot_type = 'EVENT_BLOCK' AND event_block_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL)) AND playlist_id IS NULL OR (slot_type = 'PLAYLIST' AND playlist_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL)", name='ck_clock_slot_target'),
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
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id', ondelete='RESTRICT'))
    playlist = db.relationship('Playlist')
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
        db.Index('ix_decision_stats_started', 'status', 'started_at', 'station_id'),
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
    playback_bus = db.Column(db.String(8), nullable=False, default='A')
    cart_role = db.Column(db.String(8))
    cart_position = db.Column(db.Integer)
    programming_signature = db.Column(db.String(64))
    cursor_checkpoint = db.Column(db.JSON)
    cart_mode = db.Column(db.String(8), nullable=False, default='OVER')
    duck_percent = db.Column(db.Integer, nullable=False, default=50)
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
    __table_args__ = (db.CheckConstraint("status IN ('pending','sent','failed')", name='ck_live_control_status'),db.CheckConstraint("action IN ('SKIP','TAKEOVER','FADE','DECK_LOAD','DECK_PLAY','DECK_PAUSE','DECK_CLEAR','DECK_FADE','DECK_REPEAT')",name='ck_live_control_action'))
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    idempotency_key = db.Column(db.String(36), nullable=False, unique=True)
    expected_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    target_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    deck = db.Column(db.String(1))
    fade_seconds = db.Column(db.Float, nullable=False, default=3.0, server_default='3')
    play_on_load = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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

    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
    description = db.Column(db.String(500), nullable=False, default='')
    playback_mode = db.Column(db.String(8), nullable=False, default='OVER')
    duck_percent = db.Column(db.Integer, nullable=False, default=50)
    track = db.relationship('Track')

    @property
    def playable(self):
        return self.track or self.imaging_asset

    @property
    def title(self):
        return self.track.title if self.track else self.imaging_asset.name if self.imaging_asset else 'Unassigned'


class LiveQueueSnapshot(db.Model):
    """Worker-observed socket state, stripped of paths and raw metadata."""
    __tablename__ = 'live_queue_snapshots'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    current_decision_id = db.Column(db.Integer)
    queued_decision_ids = db.Column(db.JSON, nullable=False, default=list)
    unknown_count = db.Column(db.Integer, nullable=False, default=0)
    observed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    error_code = db.Column(db.String(40))
    listeners = db.Column(db.Integer)
    broadcast_online = db.Column(db.Boolean)
    broadcast_observed_at = db.Column(db.DateTime(timezone=True))
    program_rms = db.Column(db.Float)
    mixer = db.Column(db.JSON)


class TimedEvent(db.Model):
    __tablename__ = 'timed_events'
    __table_args__ = (
        db.UniqueConstraint('uuid', name='timed_events_uuid_key'),
        db.CheckConstraint("timing_mode IN ('SOFT','HARD','NON_INTERRUPTING')", name='ck_timed_event_mode'),
        db.CheckConstraint("recurrence_type IN ('ONE_TIME','QUARTER_HOUR','HOURLY','DAILY','WEEKLY','MONTHLY')", name='ck_timed_event_recurrence'),
        db.CheckConstraint("content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK','PLAYLIST')", name='ck_timed_event_content_type'),
        db.CheckConstraint("missed_policy IN ('SKIP','PLAY_LATE')", name='ck_timed_event_missed'),
        db.CheckConstraint("interrupt_policy IN ('NEVER','MUSIC_ONLY')", name='ck_timed_event_interrupt'),
        db.CheckConstraint("(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND playlist_id IS NULL) OR (content_type='PLAYLIST' AND playlist_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL)", name='ck_timed_event_content'),
        db.CheckConstraint("(recurrence_type='ONE_TIME' AND scheduled_at_utc IS NOT NULL AND weekday IS NULL) OR (recurrence_type!='ONE_TIME' AND scheduled_at_utc IS NULL AND local_time IS NOT NULL)", name='ck_timed_event_schedule'),
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
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id', ondelete='RESTRICT'))
    playlist = db.relationship('Playlist')
    playlist_playback = db.Column(db.String(8), nullable=False, default='ONE', server_default='ONE')
    playlist_state = db.Column(db.JSON, nullable=False, default=dict, server_default='{}')
    interrupt_dj = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    month_day = db.Column(db.Integer)
    month_nth = db.Column(db.Integer)
    month_weekday = db.Column(db.Integer)
    local_date = db.Column(db.Date)
    generated_until = db.Column(db.DateTime(timezone=True))
    recurrence_type = db.Column(db.String(12), nullable=False)
    scheduled_at_utc = db.Column(db.DateTime(timezone=True))
    weekday = db.Column(db.Integer)
    weekdays = db.Column(db.String(20))
    repeat_hours = db.Column(db.JSON)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    local_time = db.Column(db.Time)
    early_tolerance_seconds = db.Column(db.Integer, nullable=False, default=0)
    late_tolerance_seconds = db.Column(db.Integer, nullable=False, default=300)
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

    @property
    def content_name(self):
        target = self.playlist or self.track or self.imaging_asset or self.event_block
        return getattr(target, 'title', None) or getattr(target, 'name', 'Unavailable audio')

    @property
    def recurrence_summary(self):
        from app.services.timed_events import recurrence_summary
        return recurrence_summary(self)

    @property
    def repeat_days(self):
        return [int(day) for day in self.weekdays.split(',')] if self.weekdays else ([self.weekday] if self.weekday is not None else [])


class TimedEventOccurrence(db.Model):
    __tablename__ = 'timed_event_occurrences'
    __table_args__ = (
        db.UniqueConstraint('timed_event_id', 'scheduled_for_utc', name='uq_timed_occurrence_instant'),
        db.CheckConstraint("state IN ('PENDING','READY','QUEUED','STARTED','COMPLETED','MISSED','FAILED','CANCELLED')", name='ck_timed_occurrence_state'),
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
    completed_at = db.Column(db.DateTime(timezone=True))
    boundary_reserved = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    cancelled_by_user = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    revision = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    runtime = db.Column(db.JSON, nullable=False, default=dict, server_default='{}')
    missed_at = db.Column(db.DateTime(timezone=True))
    failure_reason = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    event = db.relationship('TimedEvent', back_populates='occurrences')
    station = db.relationship('Station')
    selection_decision = db.relationship('SelectionDecision', foreign_keys=[selection_decision_id],
        backref=db.backref('timed_event_occurrence', uselist=False))

    @property
    def state_label(self):
        if self.state in ('PENDING','READY','QUEUED'):
            if self.failure_reason == 'waiting_for_dj': return 'Waiting for DJ'
            if self.boundary_reserved: return 'Waiting for current song'
        if self.state == 'COMPLETED' and self.failure_reason == 'partial_playback':
            return 'Completed with missing audio'
        return {'PENDING':'Scheduled','READY':'Ready','QUEUED':'Queued','STARTED':'Playing',
            'COMPLETED':'Completed','MISSED':'Missed','FAILED':'Failed','CANCELLED':'Cancelled'}.get(self.state,self.state)

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
    event_block_id = db.Column(db.Integer, db.ForeignKey('event_blocks.id', ondelete='RESTRICT'), nullable=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id', ondelete='RESTRICT'))
    playlist = db.relationship('Playlist')
    playlist_revision = db.Column(db.Integer)
    timed_event_occurrence_id = db.Column(db.Integer, db.ForeignKey('timed_event_occurrences.id', ondelete='SET NULL'), unique=True)
    clock_slot_id = db.Column(db.Integer, db.ForeignKey('clock_slots.id', ondelete='SET NULL'))
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    source = db.Column(db.String(16), nullable=False); state = db.Column(db.String(12), nullable=False, default='PENDING', index=True)
    started_at = db.Column(db.DateTime(timezone=True)); completed_at = db.Column(db.DateTime(timezone=True)); aborted_at = db.Column(db.DateTime(timezone=True))
    failure_reason = db.Column(db.String(80)); abort_requested = db.Column(db.Boolean, nullable=False, default=False); created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station'); block = db.relationship('EventBlock'); clock_slot = db.relationship('ClockSlot'); operator = db.relationship('AdminUser')
    timed_event_occurrence = db.relationship('TimedEventOccurrence', backref=db.backref('block_execution', uselist=False))
    @property
    def name(self):
        return self.playlist.name if self.playlist else self.block.name

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


class MusicEdit(db.Model):
    """Durable single-use undo for category and tag membership changes."""
    __tablename__ = 'music_edits'
    id = db.Column(db.String(36), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id'), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    changes = db.Column(db.JSON, nullable=False)
    undone = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ScheduleProgram(db.Model):
    __tablename__ = 'schedule_programs'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)
    on_date = db.Column(db.Date)
    start_minute = db.Column(db.Integer, nullable=False)
    end_minute = db.Column(db.Integer, nullable=False)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='RESTRICT'), nullable=False)
    baseline_assignment_id = db.Column(db.Integer, db.ForeignKey('schedule_assignments.id', ondelete='RESTRICT'))
    baseline_assignment = db.relationship('ScheduleAssignment')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    clock = db.relationship('Clock')
    station = db.relationship('Station')
    __table_args__ = (db.CheckConstraint('weekday BETWEEN 0 AND 6 AND start_minute BETWEEN 0 AND 1439 AND end_minute BETWEEN 1 AND 2880 AND end_minute > start_minute AND end_minute - start_minute <= 1440', name='ck_program_window'),)


class StationLogo(db.Model):
    __tablename__ = 'station_logos'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))
    thumbnail = db.deferred(db.Column(db.LargeBinary, nullable=False))
    version = db.Column(db.String(64), nullable=False)


class WebsiteSettings(db.Model):
    __tablename__ = 'website_settings'
    __table_args__ = (db.CheckConstraint('id = 1', name='ck_website_singleton'),)
    id = db.Column(db.Integer, primary_key=True, default=1)
    draft = db.Column(db.JSON, nullable=False, default=dict)
    published = db.Column(db.JSON, nullable=False, default=dict)
    revision = db.Column(db.Integer, nullable=False, default=1)


class WebsitePublication(db.Model):
    __tablename__ = 'website_publications'
    id = db.Column(db.Integer, primary_key=True)
    config = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class WebsiteAsset(db.Model):
    __tablename__ = 'website_assets'
    id = db.Column(db.String(64), primary_key=True)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))
    small = db.deferred(db.Column(db.LargeBinary, nullable=False))


class SongFlag(db.Model):
    __tablename__ = 'song_flags'
    __table_args__ = (db.UniqueConstraint('station_id', 'track_id', name='uq_song_flag_station_track'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='CASCADE'), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    note = db.Column(db.String(2000), nullable=False, default='')
    revision = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime(timezone=True))


class Playlist(db.Model):
    __tablename__ = 'playlists'
    __table_args__ = (db.CheckConstraint("mode IN ('STRAIGHT','RANDOM')", name='ck_playlist_mode'),
        db.UniqueConstraint('station_id', 'system_key', name='uq_playlist_system_key'),
        db.CheckConstraint("purpose IN ('GENERAL','STATION','COMMERCIALS')", name='ck_playlist_purpose'))
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default='')
    purpose = db.Column(db.String(12), nullable=False, default='GENERAL', server_default='GENERAL')
    system_key = db.Column(db.String(12))
    legacy_imaging_group_id = db.Column(db.Integer, unique=True)
    minimum_separation_seconds = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    mode = db.Column(db.String(12), nullable=False, default='STRAIGHT')
    revision = db.Column(db.Integer, nullable=False, default=1)
    deleted_at = db.Column(db.DateTime(timezone=True))
    station = db.relationship('Station')
    items = db.relationship('PlaylistItem', order_by='PlaylistItem.position', cascade='all, delete-orphan', back_populates='playlist')
    tracks = db.relationship('Track', secondary='playlist_items', viewonly=True, backref=db.backref('playlists', viewonly=True))

    @property
    def duration_ms(self):
        return sum(item.track.duration_ms or 0 for item in self.items)

    @property
    def enabled(self):
        return self.deleted_at is None


class PlaylistItem(db.Model):
    __tablename__ = 'playlist_items'
    __table_args__ = (db.UniqueConstraint('playlist_id', 'track_id', name='uq_playlist_track'),
                     db.UniqueConstraint('playlist_id', 'position', name='uq_playlist_position'),
                     db.CheckConstraint('position > 0', name='ck_playlist_position'))
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id', ondelete='CASCADE'), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='RESTRICT'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    playlist = db.relationship('Playlist', back_populates='items')
    track = db.relationship('Track')


class PlaylistCursor(db.Model):
    __tablename__ = 'playlist_cursors'
    __table_args__ = (db.UniqueConstraint('station_id', 'clock_slot_id', name='uq_playlist_cursor_slot'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    clock_slot_id = db.Column(db.Integer, db.ForeignKey('clock_slots.id', ondelete='CASCADE'), nullable=False)
    occurrence_key = db.Column(db.String(120), nullable=False)
    state = db.Column(db.JSON, nullable=False, default=dict)


class StationPlayerSettings(db.Model):
    __tablename__ = 'station_player_settings'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    config = db.Column(db.JSON, nullable=False, default=dict)
    revision = db.Column(db.Integer, nullable=False, default=1)
    station = db.relationship('Station', backref=db.backref('player_settings', uselist=False, cascade='all, delete-orphan'))


class StationPlayerAsset(db.Model):
    __tablename__ = 'station_player_assets'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False)
    kind = db.Column(db.String(24), nullable=False)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))
    version = db.Column(db.String(64), nullable=False)
    __table_args__ = (db.UniqueConstraint('station_id', 'kind', name='uq_player_asset'),)


class PublicScheduleRevision(db.Model):
    __tablename__ = 'public_schedule_revisions'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    entries = db.Column(db.JSON, nullable=False)
    config_revision = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class ListenerVote(db.Model):
    __tablename__ = 'listener_votes'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='CASCADE'), nullable=False)
    listener_key = db.Column(db.String(64), nullable=False)
    value = db.Column(db.Integer, nullable=False)
    decision_id = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(500), nullable=False, default='')
    review_state = db.Column(db.String(12), nullable=False, default='new')
    excluded = db.Column(db.Boolean, nullable=False, default=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    track = db.relationship('Track')
    __table_args__ = (db.UniqueConstraint('station_id', 'track_id', 'listener_key', name='uq_listener_song_vote'),
                     db.CheckConstraint('value IN (-1,0,1)', name='ck_listener_vote_value'))


class ListenerFeedbackEvent(db.Model):
    __tablename__ = 'listener_feedback_events'
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    listener_key = db.Column(db.String(64), nullable=False, index=True)
    track_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
    value = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class DMCACase(db.Model):
    __tablename__ = 'dmca_cases'
    __table_args__ = (
        db.CheckConstraint("status IN ('OPEN','REVIEWING','ACTIONED','REJECTED','CLOSED')", name='ck_dmca_status'),
        db.Index('ix_dmca_status_created', 'status', 'created_at'),
        db.Index('ix_dmca_created', 'created_at', 'id'),
        db.Index('ix_dmca_network_created', 'network_key', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(37), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(12), nullable=False, default='OPEN')
    supplied_track_id = db.Column(db.String(64), nullable=False, default='')
    station_text = db.Column(db.String(500), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'), index=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='SET NULL'), index=True)
    reported_station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='SET NULL'))
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    copyrighted_work = db.Column(db.Text, nullable=False)
    material_location = db.Column(db.Text, nullable=False)
    claimant_name = db.Column(db.String(200), nullable=False)
    claimant_email = db.Column(db.String(254), nullable=False)
    good_faith = db.Column(db.Boolean, nullable=False)
    authorized = db.Column(db.Boolean, nullable=False)
    signature = db.Column(db.String(200), nullable=False)
    network_key = db.Column(db.String(64), nullable=False)


# Serializing each random candidate also handles a concurrent collision in PostgreSQL.
@event.listens_for(Track, 'before_insert')
def assign_freo_track_id(mapper, connection, target):
    for _ in range(20):
        candidate = copyright_ids.new_track_id()
        if connection.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                               {'key': 'freo-track:' + candidate})
        if not connection.execute(select(Track.id).where(Track.freo_track_id == candidate)).first():
            target.freo_track_id = candidate
            return
    raise ValueError('Unable to allocate a unique Freo Track ID')


@event.listens_for(Track, 'before_update')
def preserve_freo_track_id(mapper, connection, target):
    if inspect(target).attrs.freo_track_id.history.has_changes():
        raise ValueError('Freo Track IDs are permanent')


@event.listens_for(Station, 'before_update')
def permanent_station_identity(mapper, connection, station):
    if inspect(station).attrs.freo_station_id.history.has_changes():
        raise ValueError('Freo Station UUID cannot be changed')


class CentralInstallation(db.Model):
    """Private local configuration; credentials live only in the worker's 0600 file."""
    __tablename__ = 'central_installation'
    __table_args__ = (db.CheckConstraint('id = 1', name='ck_central_installation_singleton'),)
    id = db.Column(db.Integer, primary_key=True, default=1)
    manager_email = db.Column(db.String(254), nullable=False, default='')
    installation_id = db.Column(db.String(36))
    registration_state = db.Column(db.String(24), nullable=False, default='unconfigured')
    license_cache = db.Column(db.JSON)
    state = db.Column(db.JSON, nullable=False, default=dict)
    last_error = db.Column(db.String(64), nullable=False, default='')


class CentralConnectionCheck(db.Model):
    """One durable manual request, separate from reporter-owned installation state."""
    __tablename__ = 'central_connection_check'
    __table_args__ = (db.CheckConstraint('id = 1', name='ck_central_connection_check_singleton'),)
    id = db.Column(db.Integer, primary_key=True, default=1)
    request_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    requested_at = db.Column(db.Float, nullable=False)
    started_at = db.Column(db.Float)
    finished_at = db.Column(db.Float)
    result = db.Column(db.JSON, nullable=False, default=dict)


class CentralStationState(db.Model):
    __tablename__ = 'central_station_state'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    last_sample = db.Column(db.JSON)
    synced_digest = db.Column(db.String(64))


class CentralHourlyMetric(db.Model):
    __tablename__ = 'central_hourly_metrics'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    period_start = db.Column(db.BigInteger, primary_key=True, index=True)
    observed_seconds = db.Column(db.Float, nullable=False, default=0)
    listener_seconds = db.Column(db.Float, nullable=False, default=0)
    peak_listeners = db.Column(db.BigInteger, nullable=False, default=0)
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    sent = db.Column(db.Boolean, nullable=False, default=False)

# Visual scheduling models share the application's metadata and station identities.
from .scheduling import (ChannelSchedule, ScheduleComposition, ScheduleCompositionRevision,
                         ScheduleTransition, ScheduleCursor)
from .statistics import (StatsState, AudienceSample, StatsBucket, AudiencePresence,
                         GeoBucket, GeoReach, StorageSnapshot, BroadcastIncident, FeedbackTransition)
from .imports import MusicImportSession, MusicImportItem
from .cue import BoothCue, SavedBoothCue, CuePlayback, CueMutation


class EventQueueCancellation(db.Model):
    __tablename__ = 'event_queue_cancellations'
    decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='CASCADE'), primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    processed = db.Column(db.Boolean, nullable=False, default=False)
    decision = db.relationship('SelectionDecision')
