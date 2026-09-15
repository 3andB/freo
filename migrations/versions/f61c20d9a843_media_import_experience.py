"""Catalog choices, artwork, waveform and explicit import activation intent."""
from alembic import op
import sqlalchemy as sa
revision = 'f61c20d9a843'
down_revision = 'e20a6b7c9012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('music_artwork', sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('station_id', sa.Integer, sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
                    sa.Column('image', sa.LargeBinary, nullable=False))
    op.create_index('ix_music_artwork_station_id', 'music_artwork', ['station_id'])
    op.add_column('media_ingest_jobs', sa.Column('import_metadata', sa.JSON, nullable=False, server_default='{}'))
    for table in ('albums', 'tracks'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('cover_id', sa.String(36)))
            batch.create_foreign_key('fk_'+table+'_cover', 'music_artwork', ['cover_id'], ['id'], ondelete='SET NULL')
    op.add_column('tracks', sa.Column('waveform', sa.JSON, nullable=False, server_default='[]'))
    op.add_column('tracks', sa.Column('auto_enable_pending', sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('tracks') as batch:
        batch.drop_column('auto_enable_pending');batch.drop_column('waveform')
    for table in ('albums', 'tracks'):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint('fk_'+table+'_cover', type_='foreignkey');batch.drop_column('cover_id')
    with op.batch_alter_table('media_ingest_jobs') as batch:
        batch.drop_column('import_metadata')
    op.drop_table('music_artwork')
