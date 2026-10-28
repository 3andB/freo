"""Broadcast codecs, confirmed metadata and external timed bulletins."""
from alembic import op
import sqlalchemy as sa
revision = 'fa06a1b2c3d4'
down_revision = 'f906a1b2c3d4'
branch_labels = None
depends_on = None

OLD_CONTENT = "(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND playlist_id IS NULL) OR (content_type='PLAYLIST' AND playlist_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL)"
NEW_CONTENT = OLD_CONTENT + " OR (content_type='BULLETIN' AND bulletin IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL)"


def upgrade():
    op.add_column('selection_decisions',sa.Column('performance_snapshot',sa.JSON()))
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_format',type_='check')
        batch.create_check_constraint('ck_stream_mounts_format',"format IN ('mp3','aac')")
        batch.alter_column('bitrate',existing_type=sa.Integer(),server_default='192')
    with op.batch_alter_table('timed_events') as batch:
        batch.add_column(sa.Column('bulletin',sa.JSON()))
        batch.drop_constraint('ck_timed_event_content_type',type_='check')
        batch.drop_constraint('ck_timed_event_content',type_='check')
        batch.create_check_constraint('ck_timed_event_content_type',"content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK','PLAYLIST','BULLETIN')")
        batch.create_check_constraint('ck_timed_event_content',NEW_CONTENT)


def downgrade():
    bind=op.get_bind()
    import json
    pending = bind.execute(sa.text('SELECT format, pending_audio FROM stream_mounts')).all()
    incompatible = any(codec != 'mp3' or (json.loads(value) if isinstance(value,str) else value) is not None for codec,value in pending)
    if bind.scalar(sa.text("SELECT count(*) FROM timed_events WHERE content_type='BULLETIN'")) or incompatible:
        raise RuntimeError('Remove bulletins and apply MP3 with no pending audio changes before downgrade.')
    with op.batch_alter_table('timed_events') as batch:
        batch.drop_constraint('ck_timed_event_content_type',type_='check')
        batch.drop_constraint('ck_timed_event_content',type_='check')
        batch.create_check_constraint('ck_timed_event_content_type',"content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK','PLAYLIST')")
        batch.create_check_constraint('ck_timed_event_content',OLD_CONTENT)
        batch.drop_column('bulletin')
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_format',type_='check')
        batch.create_check_constraint('ck_stream_mounts_format',"format = 'mp3'")
        batch.alter_column('bitrate',existing_type=sa.Integer(),server_default='128')
    op.drop_column('selection_decisions','performance_snapshot')
