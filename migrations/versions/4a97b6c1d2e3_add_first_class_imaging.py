"""Add first-class imaging, groups, and imaging clock targets.

Revision ID: 4a97b6c1d2e3
Revises: c7e7a1d55a42
"""
from alembic import op
import sqlalchemy as sa

revision = '4a97b6c1d2e3'
down_revision = 'c7e7a1d55a42'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('imaging_assets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), nullable=False, unique=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('cart_code', sa.String(32)),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('storage_key', sa.String(50), nullable=False),
        sa.Column('media_type', sa.String(12), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('bitrate_kbps', sa.Integer()),
        sa.Column('sample_rate_hz', sa.Integer(), nullable=False),
        sa.Column('channels', sa.Integer(), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('checksum_sha256', sa.String(64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('ingest_status', sa.String(12), nullable=False),
        sa.Column('decommissioned_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('station_id', 'checksum_sha256', name='uq_imaging_station_checksum'),
        sa.UniqueConstraint('station_id', 'cart_code', name='uq_imaging_station_cart_code'),
        sa.CheckConstraint("asset_type IN ('CART','STATION_ID','SWEEPER','LINER','PROMO','JINGLE','GENERIC')", name='ck_imaging_asset_type'),
        sa.CheckConstraint("ingest_status IN ('accepted','rejected')", name='ck_imaging_ingest_status'),
        sa.CheckConstraint('duration_ms > 0 AND file_size_bytes > 0', name='ck_imaging_positive_size'))
    op.create_index('ix_imaging_assets_uuid', 'imaging_assets', ['uuid'], unique=True)
    op.create_index('ix_imaging_assets_station_id', 'imaging_assets', ['station_id'])
    op.create_table('imaging_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('slug', sa.String(64), nullable=False),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('minimum_separation_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('station_id', 'slug', name='uq_imaging_group_station_slug'),
        sa.CheckConstraint('minimum_separation_seconds BETWEEN 0 AND 86400', name='ck_imaging_group_separation'))
    op.create_index('ix_imaging_groups_station_id', 'imaging_groups', ['station_id'])
    op.create_table('imaging_group_assets',
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('imaging_assets.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('imaging_groups.id', ondelete='CASCADE'), primary_key=True))
    op.add_column('clock_slots', sa.Column('imaging_asset_id', sa.Integer(), sa.ForeignKey('imaging_assets.id', ondelete='RESTRICT')))
    op.add_column('clock_slots', sa.Column('imaging_group_id', sa.Integer(), sa.ForeignKey('imaging_groups.id', ondelete='RESTRICT')))
    op.alter_column('clock_slots', 'slot_type', existing_type=sa.String(12), type_=sa.String(20), existing_nullable=False)
    op.drop_constraint('ck_clock_slot_target', 'clock_slots', type_='check')
    op.create_check_constraint('ck_clock_slot_target', 'clock_slots',
        "(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL) OR "
        "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL) OR "
        "(slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL) OR "
        "(slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL)")
    op.add_column('selection_decisions', sa.Column('imaging_asset_id', sa.Integer(), sa.ForeignKey('imaging_assets.id', ondelete='SET NULL')))
    op.add_column('selection_decisions', sa.Column('imaging_group_id', sa.Integer(), sa.ForeignKey('imaging_groups.id', ondelete='SET NULL')))
    op.add_column('selection_decisions', sa.Column('selection_method', sa.String(24), nullable=False, server_default='music'))
    op.create_check_constraint('ck_decision_one_playable', 'selection_decisions', 'track_id IS NULL OR imaging_asset_id IS NULL')
    op.add_column('media_ingest_jobs', sa.Column('imaging_asset_id', sa.Integer(), sa.ForeignKey('imaging_assets.id', ondelete='SET NULL')))
    op.add_column('media_ingest_jobs', sa.Column('imaging_type', sa.String(20)))
    op.add_column('media_ingest_jobs', sa.Column('imaging_name', sa.String(200)))
    op.add_column('media_ingest_jobs', sa.Column('cart_code', sa.String(32)))


def downgrade():
    op.drop_column('media_ingest_jobs', 'cart_code')
    op.drop_column('media_ingest_jobs', 'imaging_name')
    op.drop_column('media_ingest_jobs', 'imaging_type')
    op.drop_column('media_ingest_jobs', 'imaging_asset_id')
    op.drop_constraint('ck_decision_one_playable', 'selection_decisions', type_='check')
    op.drop_column('selection_decisions', 'selection_method')
    op.drop_column('selection_decisions', 'imaging_group_id')
    op.drop_column('selection_decisions', 'imaging_asset_id')
    op.drop_constraint('ck_clock_slot_target', 'clock_slots', type_='check')
    op.drop_column('clock_slots', 'imaging_group_id')
    op.drop_column('clock_slots', 'imaging_asset_id')
    op.alter_column('clock_slots', 'slot_type', existing_type=sa.String(20), type_=sa.String(12), existing_nullable=False)
    op.create_check_constraint('ck_clock_slot_target', 'clock_slots',
        "(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL) OR "
        "(slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL)")
    op.drop_table('imaging_group_assets')
    op.drop_table('imaging_groups')
    op.drop_table('imaging_assets')
