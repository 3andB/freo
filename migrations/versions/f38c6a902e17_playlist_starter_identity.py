"""Stable ordering for the original starter playlists.

Only adopt the original leading pair when both names still identify them.
Renamed or ambiguous playlists retain their existing identity and contents.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f38c6a902e17'
down_revision = 'e28a91bc7304'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for station_id in connection.execute(sa.text('SELECT id FROM stations')).scalars():
        rows = connection.execute(sa.text('SELECT id,name,system_key FROM playlists WHERE station_id=:station ORDER BY id LIMIT 2'), {'station':station_id}).all()
        if len(rows) == 2 and [row.name for row in rows] == ['Playlist 1','Playlist 2'] and all(row.system_key is None for row in rows):
            for number, row in enumerate(rows,1):
                connection.execute(sa.text('UPDATE playlists SET system_key=:key WHERE id=:id'), {'key':f'PLAYLIST_{number}','id':row.id})


def downgrade():
    op.get_bind().execute(sa.text("UPDATE playlists SET system_key=NULL WHERE system_key IN ('PLAYLIST_1','PLAYLIST_2')"))
