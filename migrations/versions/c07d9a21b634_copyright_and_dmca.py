"""Permanent public track identifiers and private DMCA evidence."""
from alembic import op
import sqlalchemy as sa
import secrets

revision = 'c07d9a21b634'
down_revision = 'f84c1d92be30'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tracks', sa.Column('freo_track_id', sa.String(12), nullable=True))
    connection = op.get_bind()
    used = set()
    # Metadata-only backfill: never read or rewrite original audio files.
    for identifier in connection.execute(sa.text('SELECT id FROM tracks ORDER BY id')).scalars():
        while True:
            value = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(8))
            public_id = f'FR-{value[:4]}-{value[4:]}'
            if public_id not in used:
                used.add(public_id)
                break
        connection.execute(sa.text('UPDATE tracks SET freo_track_id=:value WHERE id=:id'),
                           {'value': public_id, 'id': identifier})
    with op.batch_alter_table('tracks') as batch:
        batch.alter_column('freo_track_id', existing_type=sa.String(12), nullable=False)
        batch.create_unique_constraint('uq_tracks_freo_track_id', ['freo_track_id'])
        batch.alter_column('checksum_sha256', existing_type=sa.String(64), nullable=True)
        batch.alter_column('isrc', existing_type=sa.String(20), nullable=True)
    connection.execute(sa.text("UPDATE tracks SET isrc=NULL WHERE isrc=''"))
    op.create_table('dmca_cases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reference', sa.String(37), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('supplied_track_id', sa.String(64), nullable=False),
        sa.Column('station_text', sa.String(500), nullable=False),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='SET NULL')),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='SET NULL')),
        sa.Column('reported_station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='SET NULL')),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('copyrighted_work', sa.Text(), nullable=False),
        sa.Column('material_location', sa.Text(), nullable=False),
        sa.Column('claimant_name', sa.String(200), nullable=False),
        sa.Column('claimant_email', sa.String(254), nullable=False),
        sa.Column('good_faith', sa.Boolean(), nullable=False),
        sa.Column('authorized', sa.Boolean(), nullable=False),
        sa.Column('signature', sa.String(200), nullable=False),
        sa.Column('network_key', sa.String(64), nullable=False),
        sa.UniqueConstraint('reference', name='uq_dmca_cases_reference'),
        sa.CheckConstraint("status IN ('OPEN','REVIEWING','ACTIONED','REJECTED','CLOSED')", name='ck_dmca_status'))
    op.create_index('ix_dmca_created', 'dmca_cases', ['created_at', 'id'])
    op.create_index('ix_dmca_status_created', 'dmca_cases', ['status', 'created_at'])
    op.create_index('ix_dmca_network_created', 'dmca_cases', ['network_key', 'created_at'])
    op.create_index('ix_dmca_cases_track_id', 'dmca_cases', ['track_id'])
    op.create_index('ix_dmca_cases_station_id', 'dmca_cases', ['station_id'])


def downgrade():
    # NULL hashes cannot safely be invented for a downgrade.
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT id FROM tracks WHERE checksum_sha256 IS NULL LIMIT 1')).first():
        raise RuntimeError('Cannot downgrade while tracks have NULL checksums')
    op.drop_table('dmca_cases')
    connection.execute(sa.text("UPDATE tracks SET isrc='' WHERE isrc IS NULL"))
    with op.batch_alter_table('tracks') as batch:
        batch.drop_constraint('uq_tracks_freo_track_id', type_='unique')
        batch.drop_column('freo_track_id')
        batch.alter_column('checksum_sha256', existing_type=sa.String(64), nullable=False)
        batch.alter_column('isrc', existing_type=sa.String(20), nullable=False)
