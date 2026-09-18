"""Durable music preparation and review, separate from library ingestion."""
from alembic import op
import sqlalchemy as sa

revision = 'e92b740a613f'
down_revision = 'ab31e76f209d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('music_import_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('groups', sa.JSON(), nullable=False))
    for name in ('station_id', 'admin_user_id'):
        op.create_index('ix_music_import_sessions_' + name, 'music_import_sessions', [name])
    op.create_table('music_import_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('music_import_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('relative_path', sa.String(1000), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('detected', sa.JSON(), nullable=False),
        sa.Column('choices', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('error', sa.String(240), nullable=False),
        sa.Column('preview_id', sa.String(36)),
        sa.Column('artwork', sa.LargeBinary()),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('media_ingest_jobs.id', ondelete='SET NULL')),
        sa.Column('dismissed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','preparing','ready','failed','finalized','cancelled','expired')", name='ck_music_import_item_status'))
    for name in ('session_id', 'status'):
        op.create_index('ix_music_import_items_' + name, 'music_import_items', [name])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM music_import_items WHERE status IN ('pending','preparing','ready')")).scalar():
        raise RuntimeError('Finish or cancel music import drafts before downgrading')
    op.drop_table('music_import_items')
    op.drop_table('music_import_sessions')
