"""Add ordered event blocks and execution snapshots.

Revision ID: c91d2e3f4a56
Revises: b7e14f9c203d
"""
from alembic import op
import sqlalchemy as sa

revision='c91d2e3f4a56'; down_revision='b7e14f9c203d'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('event_blocks',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),sa.Column('slug',sa.String(64),nullable=False),sa.Column('description',sa.String(500),nullable=False),
        sa.Column('block_type',sa.String(20),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('failure_policy',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('station_id','slug',name='uq_event_block_station_slug'),
        sa.CheckConstraint("block_type IN ('GENERIC','STOPSET','NEWS','LEGAL_ID','PROMO_BLOCK','SPECIAL')",name='ck_event_block_type'),
        sa.CheckConstraint("failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')",name='ck_event_block_failure_policy'))
    op.create_index('ix_event_blocks_station_id','event_blocks',['station_id'])
    op.create_table('event_block_items',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('event_block_id',sa.Integer(),sa.ForeignKey('event_blocks.id',ondelete='CASCADE'),nullable=False),
        sa.Column('position',sa.Integer(),nullable=False),sa.Column('item_type',sa.String(20),nullable=False),
        sa.Column('track_id',sa.Integer(),sa.ForeignKey('tracks.id',ondelete='RESTRICT')),sa.Column('imaging_asset_id',sa.Integer(),sa.ForeignKey('imaging_assets.id',ondelete='RESTRICT')),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('label',sa.String(120)),sa.Column('failure_policy',sa.String(20)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('event_block_id','position',name='uq_event_block_item_position'),sa.CheckConstraint('position > 0',name='ck_event_block_item_position'),
        sa.CheckConstraint("item_type IN ('TRACK','IMAGING_ASSET')",name='ck_event_block_item_type'),
        sa.CheckConstraint("failure_policy IS NULL OR failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')",name='ck_event_block_item_failure_policy'),
        sa.CheckConstraint("(item_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL)",name='ck_event_block_item_target'))
    op.create_index('ix_event_block_items_event_block_id','event_block_items',['event_block_id'])
    with op.batch_alter_table('clock_slots') as b: b.add_column(sa.Column('event_block_id',sa.Integer(),sa.ForeignKey('event_blocks.id',ondelete='RESTRICT')))
    with op.batch_alter_table('timed_events') as b: b.add_column(sa.Column('event_block_id',sa.Integer(),sa.ForeignKey('event_blocks.id',ondelete='RESTRICT')))
    # Existing CHECK constraints must include the new nullable target.
    if op.get_context().dialect.name == 'postgresql':
        op.drop_constraint('ck_clock_slot_target','clock_slots',type_='check'); op.drop_constraint('ck_timed_event_content_type','timed_events',type_='check'); op.drop_constraint('ck_timed_event_content','timed_events',type_='check'); op.drop_constraint('ck_imaging_asset_type','imaging_assets',type_='check')
        op.create_check_constraint('ck_clock_slot_target','clock_slots',"(slot_type='ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type='CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type='CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type='IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR (slot_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL)")
        op.create_check_constraint('ck_timed_event_content_type','timed_events',"content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK')")
        op.create_check_constraint('ck_timed_event_content','timed_events',"(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL AND event_block_id IS NULL) OR (content_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL)")
        op.create_check_constraint('ck_imaging_asset_type','imaging_assets',"asset_type IN ('CART','STATION_ID','SWEEPER','LINER','PROMO','JINGLE','COMMERCIAL','GENERIC')")
    op.create_table('event_block_executions',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),sa.Column('event_block_id',sa.Integer(),sa.ForeignKey('event_blocks.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('timed_event_occurrence_id',sa.Integer(),sa.ForeignKey('timed_event_occurrences.id',ondelete='SET NULL'),unique=True),sa.Column('clock_slot_id',sa.Integer(),sa.ForeignKey('clock_slots.id',ondelete='SET NULL')),sa.Column('admin_user_id',sa.Integer(),sa.ForeignKey('admin_users.id',ondelete='SET NULL')),
        sa.Column('source',sa.String(16),nullable=False),sa.Column('state',sa.String(12),nullable=False),sa.Column('started_at',sa.DateTime(timezone=True)),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('aborted_at',sa.DateTime(timezone=True)),sa.Column('failure_reason',sa.String(80)),sa.Column('abort_requested',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("state IN ('PENDING','QUEUED','STARTED','COMPLETED','ABORTED','FAILED','CANCELLED')",name='ck_block_execution_state'),sa.CheckConstraint("source IN ('TIMED_EVENT','CLOCK','MANUAL')",name='ck_block_execution_source'))
    op.create_index('ix_event_block_executions_station_id','event_block_executions',['station_id']); op.create_index('ix_event_block_executions_state','event_block_executions',['state'])
    op.create_table('event_block_item_executions',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('block_execution_id',sa.Integer(),sa.ForeignKey('event_block_executions.id',ondelete='CASCADE'),nullable=False),sa.Column('event_block_item_id',sa.Integer(),sa.ForeignKey('event_block_items.id',ondelete='SET NULL')),sa.Column('position',sa.Integer(),nullable=False),sa.Column('item_type',sa.String(20),nullable=False),sa.Column('track_id',sa.Integer(),sa.ForeignKey('tracks.id',ondelete='RESTRICT')),sa.Column('imaging_asset_id',sa.Integer(),sa.ForeignKey('imaging_assets.id',ondelete='RESTRICT')),sa.Column('label',sa.String(120)),sa.Column('failure_policy',sa.String(20),nullable=False),sa.Column('state',sa.String(12),nullable=False),sa.Column('selection_decision_id',sa.Integer(),sa.ForeignKey('selection_decisions.id',ondelete='SET NULL'),unique=True),sa.Column('queued_at',sa.DateTime(timezone=True)),sa.Column('started_at',sa.DateTime(timezone=True)),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('failed_at',sa.DateTime(timezone=True)),sa.Column('failure_reason',sa.String(80)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('block_execution_id','position',name='uq_block_item_execution_position'),sa.CheckConstraint("state IN ('PENDING','QUEUED','STARTED','COMPLETED','SKIPPED','FAILED')",name='ck_block_item_execution_state'),sa.CheckConstraint("item_type IN ('TRACK','IMAGING_ASSET')",name='ck_block_item_execution_type'),sa.CheckConstraint("failure_policy IN ('SKIP_FAILED_ITEM','ABORT_BLOCK')",name='ck_block_item_execution_policy'),sa.CheckConstraint("(item_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL)",name='ck_block_item_execution_target'))
    op.create_index('ix_event_block_item_executions_block_execution_id','event_block_item_executions',['block_execution_id'])

def downgrade():
    op.drop_table('event_block_item_executions'); op.drop_table('event_block_executions')
    with op.batch_alter_table('timed_events') as b: b.drop_column('event_block_id')
    with op.batch_alter_table('clock_slots') as b: b.drop_column('event_block_id')
    op.drop_table('event_block_items'); op.drop_table('event_blocks')
