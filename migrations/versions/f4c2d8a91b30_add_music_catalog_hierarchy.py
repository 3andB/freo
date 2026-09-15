"""Add Artist, Album, Song metadata, analysis, and station tags.

Revision ID: f4c2d8a91b30
Revises: e7a13c9d2f01
"""
from alembic import op
import sqlalchemy as sa

revision='f4c2d8a91b30';down_revision='e7a13c9d2f01';branch_labels=None;depends_on=None


def upgrade():
    op.create_table('artists',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('normalized_name',sa.String(200),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('station_id','normalized_name',name='uq_artist_station_name'))
    op.create_index('ix_artists_station_id','artists',['station_id'])
    op.create_table('albums',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),sa.Column('artist_id',sa.Integer(),sa.ForeignKey('artists.id',ondelete='RESTRICT'),nullable=False),sa.Column('title',sa.String(200),nullable=False),sa.Column('normalized_title',sa.String(200),nullable=False),sa.Column('album_artist',sa.String(200),nullable=False,server_default=''),sa.Column('release_year',sa.Integer()),sa.Column('genre',sa.String(100),nullable=False,server_default=''),sa.Column('artwork_key',sa.String(50)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('station_id','artist_id','normalized_title',name='uq_album_station_artist_title'))
    op.create_index('ix_albums_station_id','albums',['station_id']);op.create_index('ix_albums_artist_id','albums',['artist_id'])
    op.create_table('music_tags',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),sa.Column('name',sa.String(80),nullable=False),sa.Column('slug',sa.String(80),nullable=False),sa.UniqueConstraint('station_id','slug',name='uq_music_tag_station_slug'))
    op.create_index('ix_music_tags_station_id','music_tags',['station_id'])
    with op.batch_alter_table('tracks') as b:
        b.add_column(sa.Column('artist_id',sa.Integer(),sa.ForeignKey('artists.id',ondelete='RESTRICT')));b.add_column(sa.Column('album_id',sa.Integer(),sa.ForeignKey('albums.id',ondelete='SET NULL')))
        b.add_column(sa.Column('album_artist',sa.String(200),nullable=False,server_default=''));b.add_column(sa.Column('track_number',sa.Integer()));b.add_column(sa.Column('disc_number',sa.Integer()));b.add_column(sa.Column('release_year',sa.Integer()));b.add_column(sa.Column('genre',sa.String(100),nullable=False,server_default=''));b.add_column(sa.Column('isrc',sa.String(20),nullable=False,server_default=''));b.add_column(sa.Column('artwork_key',sa.String(50)));b.add_column(sa.Column('bpm',sa.Float()));b.add_column(sa.Column('loudness_lufs',sa.Float()));b.add_column(sa.Column('true_peak_db',sa.Float()));b.add_column(sa.Column('cue_in_ms',sa.Integer()));b.add_column(sa.Column('cue_out_ms',sa.Integer()));b.add_column(sa.Column('segue_ms',sa.Integer()));b.add_column(sa.Column('analysis_status',sa.String(16),nullable=False,server_default='pending'));b.add_column(sa.Column('scheduling_restrictions',sa.JSON(),nullable=False,server_default='{}'))
        b.create_index('ix_tracks_artist_id',['artist_id']);b.create_index('ix_tracks_album_id',['album_id'])
    now="CURRENT_TIMESTAMP"
    op.execute(f"INSERT INTO artists (station_id,name,normalized_name,created_at,updated_at) SELECT station_id,min(artist),lower(trim(artist)),{now},{now} FROM tracks GROUP BY station_id,lower(trim(artist))")
    op.execute("UPDATE tracks t SET artist_id=a.id FROM artists a WHERE a.station_id=t.station_id AND a.normalized_name=lower(trim(t.artist))")
    op.execute(f"INSERT INTO albums (station_id,artist_id,title,normalized_title,album_artist,genre,created_at,updated_at) SELECT t.station_id,t.artist_id,min(t.album),lower(trim(t.album)),'','',{now},{now} FROM tracks t WHERE trim(t.album)<>'' GROUP BY t.station_id,t.artist_id,lower(trim(t.album))")
    op.execute("UPDATE tracks t SET album_id=a.id FROM albums a WHERE a.station_id=t.station_id AND a.artist_id=t.artist_id AND a.normalized_title=lower(trim(t.album))")
    op.create_table('song_tags',sa.Column('track_id',sa.Integer(),sa.ForeignKey('tracks.id',ondelete='CASCADE'),primary_key=True),sa.Column('tag_id',sa.Integer(),sa.ForeignKey('music_tags.id',ondelete='CASCADE'),primary_key=True))


def downgrade():
    op.drop_table('song_tags')
    with op.batch_alter_table('tracks') as b:
        b.drop_index('ix_tracks_album_id');b.drop_index('ix_tracks_artist_id')
        for column in ('scheduling_restrictions','analysis_status','segue_ms','cue_out_ms','cue_in_ms','true_peak_db','loudness_lufs','bpm','artwork_key','isrc','genre','release_year','disc_number','track_number','album_artist','album_id','artist_id'): b.drop_column(column)
    op.drop_table('music_tags');op.drop_table('albums');op.drop_table('artists')
