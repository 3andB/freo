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


IMAGING_TYPES = ('CART', 'STATION_ID', 'SWEEPER', 'LINER', 'PROMO', 'JINGLE', 'GENERIC')


class ImagingAsset(db.Model):
    __tablename__ = 'imaging_assets'
    __table_args__ = (
        db.UniqueConstraint('station_id', 'checksum_sha256', name='uq_imaging_station_checksum'),
        db.UniqueConstraint('station_id', 'cart_code', name='uq_imaging_station_cart_code'),
        db.CheckConstraint("asset_type IN ('CART','STATION_ID','SWEEPER','LINER','PROMO','JINGLE','GENERIC')", name='ck_imaging_asset_type'),
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


class ClockSlot(db.Model):
    __tablename__ = 'clock_slots'
    __table_args__ = (
        db.UniqueConstraint('clock_id', 'position', name='uq_clock_slot_position'),
        db.CheckConstraint('position > 0', name='ck_clock_slot_position'),
        db.CheckConstraint("(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL) OR "
                           "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL) OR "
                           "(slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL) OR "
                           "(slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL)", name='ck_clock_slot_target'),
    )
    id = db.Column(db.Integer, primary_key=True)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    slot_type = db.Column(db.String(20), nullable=False)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='RESTRICT'))
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='RESTRICT'))
    imaging_asset_id = db.Column(db.Integer, db.ForeignKey('imaging_assets.id', ondelete='RESTRICT'))
    imaging_group_id = db.Column(db.Integer, db.ForeignKey('imaging_groups.id', ondelete='RESTRICT'))
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    label = db.Column(db.String(120))
    clock = db.relationship('Clock', back_populates='slots')
    rotation = db.relationship('Rotation')
    category = db.relationship('MediaCategory')
    imaging_asset = db.relationship('ImagingAsset')
    imaging_group = db.relationship('ImagingGroup')


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
    __table_args__ = (db.CheckConstraint("status IN ('pending','sent','failed')", name='ck_live_control_status'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id', ondelete='SET NULL'))
    idempotency_key = db.Column(db.String(36), nullable=False, unique=True)
    expected_decision_id = db.Column(db.Integer, db.ForeignKey('selection_decisions.id', ondelete='SET NULL'))
    status = db.Column(db.String(12), nullable=False, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime(timezone=True))
    error_code = db.Column(db.String(40))
    station = db.relationship('Station')
    operator = db.relationship('AdminUser')
    expected_decision = db.relationship('SelectionDecision')


class LiveQueueSnapshot(db.Model):
    """Worker-observed socket state, stripped of paths and raw metadata."""
    __tablename__ = 'live_queue_snapshots'
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True)
    current_decision_id = db.Column(db.Integer)
    queued_decision_ids = db.Column(db.JSON, nullable=False, default=list)
    unknown_count = db.Column(db.Integer, nullable=False, default=0)
    observed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    error_code = db.Column(db.String(40))


class AutomationHeartbeat(db.Model):
    __tablename__ = 'automation_heartbeat'
    id = db.Column(db.Integer, primary_key=True)
    seen_at = db.Column(db.DateTime(timezone=True), nullable=False)
