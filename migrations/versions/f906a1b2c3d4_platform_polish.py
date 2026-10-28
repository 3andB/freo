"""Optional public discovery/profiles and 192 kbps output support."""
from alembic import op
import sqlalchemy as sa

revision = 'f906a1b2c3d4'
down_revision = 'f806a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('tracks', 'artists'):
        op.add_column(table, sa.Column('discovery_links', sa.JSON(), nullable=False, server_default='[]'))
    for name in ('width', 'height'):
        op.add_column('station_player_assets', sa.Column(name, sa.Integer()))
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_bitrate', type_='check')
        batch.create_check_constraint('ck_stream_mounts_bitrate', 'bitrate IN (64,96,128,192)')
        batch.alter_column('bitrate', existing_type=sa.Integer(), server_default='128')
    op.create_table('dj_station_profiles',
        sa.Column('user_id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), primary_key=True),
        sa.Column('bio', sa.String(1000), nullable=False, server_default=''),
        sa.Column('links', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('image', sa.LargeBinary()), sa.Column('image_version', sa.String(64)),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(['user_id', 'station_id'],
            ['dj_station_assignments.admin_user_id', 'dj_station_assignments.station_id'], ondelete='CASCADE'))


def downgrade():
    rows = op.get_bind().execute(sa.text('SELECT bitrate, pending_audio FROM stream_mounts')).all()
    import json
    for bitrate, pending in rows:
        pending = json.loads(pending) if isinstance(pending, str) else pending
        if bitrate == 192 or (pending or {}).get('bitrate') == 192:
            raise RuntimeError('Apply a lower bitrate and clear pending 192 kbps changes before downgrading.')
    op.drop_table('dj_station_profiles')
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_bitrate', type_='check')
        batch.create_check_constraint('ck_stream_mounts_bitrate', 'bitrate IN (64,96,128)')
        batch.alter_column('bitrate', existing_type=sa.Integer(), server_default=None)
    for name in ('height', 'width'):
        op.drop_column('station_player_assets', name)
    for table in ('artists', 'tracks'):
        op.drop_column(table, 'discovery_links')
