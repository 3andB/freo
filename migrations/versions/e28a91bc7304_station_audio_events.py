"""Station audio collections and local recurring playlist events.

Legacy Imaging rows remain readable until the resumable media conversion runs.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e28a91bc7304'
down_revision = 'ab28c910d642'
branch_labels = None
depends_on = None

RECURRENCE = "recurrence_type IN ('ONE_TIME','QUARTER_HOUR','HOURLY','DAILY','WEEKLY','MONTHLY')"
CONTENT = "content_type IN ('TRACK','IMAGING_ASSET','EVENT_BLOCK','PLAYLIST')"
TARGET = "(content_type='TRACK' AND track_id IS NOT NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='IMAGING_ASSET' AND imaging_asset_id IS NOT NULL AND track_id IS NULL AND event_block_id IS NULL AND playlist_id IS NULL) OR (content_type='EVENT_BLOCK' AND event_block_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND playlist_id IS NULL) OR (content_type='PLAYLIST' AND playlist_id IS NOT NULL AND track_id IS NULL AND imaging_asset_id IS NULL AND event_block_id IS NULL)"
SCHEDULE = "(recurrence_type='ONE_TIME' AND scheduled_at_utc IS NOT NULL AND weekday IS NULL) OR (recurrence_type!='ONE_TIME' AND scheduled_at_utc IS NULL AND local_time IS NOT NULL)"


def upgrade():
    with op.batch_alter_table('tracks') as batch:
        batch.add_column(sa.Column('audio_kind',sa.String(12),nullable=False,server_default='MUSIC'))
        batch.add_column(sa.Column('audio_subtype',sa.String(24),nullable=False,server_default=''))
        batch.add_column(sa.Column('cart_code',sa.String(40)))
        batch.add_column(sa.Column('legacy_imaging_id',sa.Integer()))
        batch.create_unique_constraint('uq_track_legacy_imaging','legacy_imaging_id'.split())
        batch.create_check_constraint('ck_track_audio_kind',"audio_kind IN ('MUSIC','STATION','COMMERCIALS')")
        batch.create_index('ix_tracks_audio_kind',['audio_kind'])
    with op.batch_alter_table('playlists') as batch:
        batch.add_column(sa.Column('purpose',sa.String(12),nullable=False,server_default='GENERAL'))
        batch.add_column(sa.Column('system_key',sa.String(12)))
        batch.add_column(sa.Column('legacy_imaging_group_id',sa.Integer()))
        batch.create_unique_constraint('uq_playlist_legacy_group',['legacy_imaging_group_id'])
        batch.add_column(sa.Column('minimum_separation_seconds',sa.Integer(),nullable=False,server_default='0'))
        batch.create_unique_constraint('uq_playlist_system_key',['station_id','system_key'])
        batch.create_check_constraint('ck_playlist_purpose',"purpose IN ('GENERAL','STATION','COMMERCIALS')")
    bind=op.get_bind()
    for kind in ('STATION','COMMERCIALS'):
        bind.execute(sa.text("INSERT INTO playlists (station_id,name,description,mode,revision,purpose,system_key) SELECT id,:kind,:description,'STRAIGHT',1,:kind,:kind FROM stations"),dict(kind=kind,description=f'All {kind.lower()} audio for this station'))
    with op.batch_alter_table('timed_events') as batch:
        batch.add_column(sa.Column('playlist_id',sa.Integer()))
        batch.create_foreign_key('fk_event_playlist','playlists',['playlist_id'],['id'],ondelete='RESTRICT')
        for name,typ,default in [('playlist_playback',sa.String(8),'ONE'),('playlist_state',sa.JSON(),'{}'),('interrupt_dj',sa.Boolean(),sa.false()),('revision',sa.Integer(),'1')]:
            batch.add_column(sa.Column(name,typ,nullable=False,server_default=default))
        for name,typ in [('month_day',sa.Integer()),('month_nth',sa.Integer()),('month_weekday',sa.Integer()),('local_date',sa.Date()),('generated_until',sa.DateTime(timezone=True))]: batch.add_column(sa.Column(name,typ))
        for name,expression in [('ck_timed_event_recurrence',RECURRENCE),('ck_timed_event_content_type',CONTENT),('ck_timed_event_content',TARGET),('ck_timed_event_schedule',SCHEDULE)]:
            batch.drop_constraint(name,type_='check');batch.create_check_constraint(name,expression)
    with op.batch_alter_table('timed_event_occurrences') as batch:
        batch.add_column(sa.Column('completed_at',sa.DateTime(timezone=True)))
        for name in ('boundary_reserved','cancelled_by_user'):batch.add_column(sa.Column(name,sa.Boolean(),nullable=False,server_default=sa.false()))
        batch.add_column(sa.Column('revision',sa.Integer(),nullable=False,server_default='1'))
        batch.add_column(sa.Column('runtime',sa.JSON(),nullable=False,server_default='{}'))
        batch.drop_constraint('ck_timed_occurrence_state',type_='check')
        batch.create_check_constraint('ck_timed_occurrence_state',"state IN ('PENDING','READY','QUEUED','STARTED','COMPLETED','MISSED','FAILED','CANCELLED')")
        batch.create_index('ix_event_due',['station_id','state','scheduled_for_utc'])
    with op.batch_alter_table('event_block_executions') as batch:
        batch.alter_column('event_block_id',existing_type=sa.Integer(),nullable=True)
        batch.add_column(sa.Column('playlist_id',sa.Integer()))
        batch.add_column(sa.Column('playlist_revision',sa.Integer()))
        batch.create_foreign_key('fk_execution_playlist','playlists',['playlist_id'],['id'],ondelete='RESTRICT')
    for table in ('commercial_creatives','traffic_stopset_items'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('track_id',sa.Integer()))
            batch.create_foreign_key('fk_'+table+'_track','tracks',['track_id'],['id'],ondelete='RESTRICT')
            if table=='commercial_creatives':batch.alter_column('imaging_asset_id',existing_type=sa.Integer(),nullable=True)
            else:
                batch.drop_constraint('ck_stopset_item_target',type_='check')
                batch.create_check_constraint('ck_stopset_item_target',"(item_type='FIXED_IMAGING' AND imaging_asset_id IS NOT NULL AND track_id IS NULL) OR (item_type='FIXED_AUDIO' AND track_id IS NOT NULL AND imaging_asset_id IS NULL) OR (item_type='COMMERCIAL_SLOT' AND imaging_asset_id IS NULL AND track_id IS NULL)")
    op.create_table('event_queue_cancellations',
        sa.Column('decision_id',sa.Integer(),sa.ForeignKey('selection_decisions.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('processed',sa.Boolean(),nullable=False))
    op.create_index('ix_event_queue_cancellations_station_id','event_queue_cancellations',['station_id'])


def downgrade():
    raise RuntimeError('Restore the database and media backup to roll back unified station audio and event executions.')
