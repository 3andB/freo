"""Audio formats, daily import reminder and queued station audio settings."""
from alembic import op
import sqlalchemy as sa

revision = 'c84a2e019b36'
down_revision = 'b185c9a027d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_users', sa.Column('import_notice_date', sa.Date()))
    op.add_column('tracks', sa.Column('preview_key', sa.String(50)))
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_bitrate', type_='check')
        batch.create_check_constraint('ck_stream_mounts_bitrate', 'bitrate IN (64,96,128)')
        batch.add_column(sa.Column('audio_processing', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('pending_audio', sa.JSON()))
        batch.add_column(sa.Column('audio_status', sa.String(12), nullable=False, server_default='ready'))
        batch.add_column(sa.Column('audio_error', sa.String(240), nullable=False, server_default=''))
        batch.add_column(sa.Column('audio_revision', sa.Integer(), nullable=False, server_default='1'))
        batch.create_check_constraint('ck_stream_mounts_audio_status', "audio_status IN ('ready','pending','applying','failed')")


def downgrade():
    # A downgrade must not silently change a live encoder's bitrate.
    connection = op.get_bind()
    import json
    rows = connection.execute(sa.text('SELECT bitrate, audio_status, audio_processing FROM stream_mounts')).all()
    if any(rate != 64 or status != 'ready' or any((json.loads(processing) if isinstance(processing, str) else processing).get(key) for key in ('agc', 'eq', 'multiband')) for rate, status, processing in rows):
        raise RuntimeError('Restore 64 kbps and disable processing on every station before downgrading')
    if connection.execute(sa.text("SELECT COUNT(*) FROM tracks WHERE preview_key IS NOT NULL OR (media_type <> 'mp3' AND deleted_at IS NULL)")).scalar():
        raise RuntimeError('Export and remove WAV, M4A and FLAC songs before downgrading to the MP3-only importer')
    with op.batch_alter_table('stream_mounts') as batch:
        batch.drop_constraint('ck_stream_mounts_audio_status', type_='check')
        batch.drop_constraint('ck_stream_mounts_bitrate', type_='check')
        batch.create_check_constraint('ck_stream_mounts_bitrate', 'bitrate = 64')
        for column in ('audio_processing', 'pending_audio', 'audio_status', 'audio_error', 'audio_revision'):
            batch.drop_column(column)
    with op.batch_alter_table('tracks') as batch:
        batch.drop_column('preview_key')
    with op.batch_alter_table('admin_users') as batch:
        batch.drop_column('import_notice_date')
