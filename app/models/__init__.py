from datetime import datetime, timezone

from app.extensions import db


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


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
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    station = db.relationship('Station', backref=db.backref('tracks', lazy='dynamic'))


track_categories = db.Table(
    'track_categories',
    db.Column('track_id', db.Integer, db.ForeignKey('tracks.id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('media_categories.id', ondelete='CASCADE'), primary_key=True),
)


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
        db.CheckConstraint("(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL) OR "
                           "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL)", name='ck_clock_slot_target'),
    )
    id = db.Column(db.Integer, primary_key=True)
    clock_id = db.Column(db.Integer, db.ForeignKey('clocks.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    slot_type = db.Column(db.String(12), nullable=False)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='RESTRICT'))
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='RESTRICT'))
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    label = db.Column(db.String(120))
    clock = db.relationship('Clock', back_populates='slots')
    rotation = db.relationship('Rotation')
    category = db.relationship('MediaCategory')


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
    __table_args__ = (db.CheckConstraint("status IN ('selected','queued','started','failed')", name='ck_decision_status'),)
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False, index=True)
    rotation_id = db.Column(db.Integer, db.ForeignKey('rotations.id', ondelete='SET NULL'))
    slot_id = db.Column(db.Integer, db.ForeignKey('rotation_slots.id', ondelete='SET NULL'))
    category_id = db.Column(db.Integer, db.ForeignKey('media_categories.id', ondelete='SET NULL'))
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id', ondelete='SET NULL'))
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
    category = db.relationship('MediaCategory')
    slot = db.relationship('RotationSlot')
    clock = db.relationship('Clock')
    clock_slot = db.relationship('ClockSlot')
    schedule_assignment = db.relationship('ScheduleAssignment')


class AutomationHeartbeat(db.Model):
    __tablename__ = 'automation_heartbeat'
    id = db.Column(db.Integer, primary_key=True)
    seen_at = db.Column(db.DateTime(timezone=True), nullable=False)
