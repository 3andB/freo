"""Keep legacy Imaging identities separate from music with identical bytes."""
from alembic import op
import sqlalchemy as sa

revision = 'fc06a1b2c3d4'
down_revision = 'fb06a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tracks') as batch:
        batch.drop_constraint('uq_tracks_station_checksum', type_='unique')
    op.create_index('uq_tracks_station_checksum', 'tracks', ['station_id', 'checksum_sha256'],
                    unique=True, postgresql_where=sa.text('legacy_imaging_id IS NULL'),
                    sqlite_where=sa.text('legacy_imaging_id IS NULL'))


def downgrade():
    # Never delete/reclassify duplicate legacy audio to make a downgrade fit.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM tracks WHERE checksum_sha256 IS NOT NULL GROUP BY station_id, checksum_sha256 HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError('Recover the matched backup; duplicate legacy audio prevents this downgrade')
    op.drop_index('uq_tracks_station_checksum', table_name='tracks')
    with op.batch_alter_table('tracks') as batch:
        batch.create_unique_constraint('uq_tracks_station_checksum', ['station_id', 'checksum_sha256'])
