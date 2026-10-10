"""Station playlists, ordered membership, and durable playback progress."""
from alembic import op
import sqlalchemy as sa
revision = 'f73b8c9012ab'
down_revision = 'a09f6d3e82b1'
branch_labels = None
depends_on = None

OLD_TARGET = "(slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'EVENT_BLOCK' AND event_block_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL)"
NEW_TARGET = "((slot_type = 'ROTATION' AND rotation_id IS NOT NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'CATEGORY' AND category_id IS NOT NULL AND rotation_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'CART' AND imaging_asset_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'IMAGING_GROUP' AND imaging_group_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL) OR (slot_type = 'EVENT_BLOCK' AND event_block_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL)) AND playlist_id IS NULL OR (slot_type = 'PLAYLIST' AND playlist_id IS NOT NULL AND rotation_id IS NULL AND category_id IS NULL AND imaging_asset_id IS NULL AND imaging_group_id IS NULL AND event_block_id IS NULL)"

def upgrade():
    op.create_table('playlists',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),
        sa.Column('description',sa.String(500),nullable=False),
        sa.Column('mode',sa.String(12),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('deleted_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('STRAIGHT','RANDOM')",name='ck_playlist_mode'))
    op.create_index('ix_playlists_station_id','playlists',['station_id'])
    op.create_table('playlist_items',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('playlist_id',sa.Integer(),sa.ForeignKey('playlists.id',ondelete='CASCADE'),nullable=False),
        sa.Column('track_id',sa.Integer(),sa.ForeignKey('tracks.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('position',sa.Integer(),nullable=False),
        sa.UniqueConstraint('playlist_id','track_id',name='uq_playlist_track'),
        sa.UniqueConstraint('playlist_id','position',name='uq_playlist_position'),
        sa.CheckConstraint('position > 0',name='ck_playlist_position'))
    op.create_index('ix_playlist_items_playlist_id','playlist_items',['playlist_id'])
    with op.batch_alter_table('clock_slots') as batch:
        batch.add_column(sa.Column('playlist_id',sa.Integer()))
        batch.create_foreign_key('fk_clock_slot_playlist','playlists',['playlist_id'],['id'],ondelete='RESTRICT')
        batch.drop_constraint('ck_clock_slot_target',type_='check')
        batch.create_check_constraint('ck_clock_slot_target',NEW_TARGET)
    op.create_table('playlist_cursors',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('clock_slot_id',sa.Integer(),sa.ForeignKey('clock_slots.id',ondelete='CASCADE'),nullable=False),
        sa.Column('occurrence_key',sa.String(120),nullable=False),
        sa.Column('state',sa.JSON(),nullable=False),
        sa.UniqueConstraint('station_id','clock_slot_id',name='uq_playlist_cursor_slot'))
    op.create_index('ix_playlist_cursors_station_id','playlist_cursors',['station_id'])
    connection=op.get_bind()
    for station_id in connection.execute(sa.text('SELECT id FROM stations')):
        for number in (1,2):
            connection.execute(sa.text("INSERT INTO playlists (station_id,name,description,mode,revision) VALUES (:station,:name,'','STRAIGHT',1)"),dict(station=station_id[0],name=f'Playlist {number}'))


def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM clock_slots WHERE playlist_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError('Remove playlist program clocks before downgrading; existing programs were preserved')
    op.drop_table('playlist_cursors')
    with op.batch_alter_table('clock_slots') as batch:
        batch.drop_constraint('ck_clock_slot_target',type_='check')
        batch.drop_constraint('fk_clock_slot_playlist',type_='foreignkey')
        batch.drop_column('playlist_id')
        batch.create_check_constraint('ck_clock_slot_target',OLD_TARGET)
    op.drop_table('playlist_items')
    op.drop_table('playlists')
