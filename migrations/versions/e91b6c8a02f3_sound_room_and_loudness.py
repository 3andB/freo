"""Sound Room notes, tags, analysis scheduling, and station loudness."""
from alembic import op
import sqlalchemy as sa
revision='e91b6c8a02f3'
down_revision='d8a4b37f20ce'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('stations',sa.Column('target_lufs',sa.Float(),nullable=False,server_default='-16'))
    op.add_column('music_tags',sa.Column('color',sa.String(7),nullable=False,server_default='#b9e79b'))
    for column in [
        sa.Column('deleted_at',sa.DateTime(timezone=True)),
        sa.Column('notes',sa.Text(),nullable=False,server_default=''),
        sa.Column('analysis_requested',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('analysis_attempts',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('analysis_started_at',sa.DateTime(timezone=True)),
        sa.Column('analyzed_at',sa.DateTime(timezone=True)),
        sa.Column('analysis_retry_at',sa.DateTime(timezone=True)),
        sa.Column('analysis_error',sa.String(240),nullable=False,server_default=''),
    ]: op.add_column('tracks',column)
    op.execute("UPDATE tracks SET analysis_status='pending' WHERE analysis_status='complete' AND (loudness_lufs IS NULL OR true_peak_db IS NULL)")
    op.create_table('music_edits',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id'),nullable=False),
        sa.Column('admin_user_id',sa.Integer(),sa.ForeignKey('admin_users.id'),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False),sa.Column('target_id',sa.Integer(),nullable=False),
        sa.Column('changes',sa.JSON(),nullable=False),sa.Column('undone',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))


def downgrade():
    op.drop_table('music_edits')
    for name in ('deleted_at','notes','analysis_requested','analysis_attempts','analysis_started_at','analyzed_at','analysis_retry_at','analysis_error'):op.drop_column('tracks',name)
    op.drop_column('music_tags','color');op.drop_column('stations','target_lufs')
