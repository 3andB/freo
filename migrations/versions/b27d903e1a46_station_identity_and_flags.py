"""Station identity and station-specific song review flags."""
from alembic import op
import sqlalchemy as sa
revision = 'b27d903e1a46'
down_revision = 'ea640b19c275'
branch_labels = None
depends_on = None


def upgrade():
    for name, length in [('city',120),('region',120),('contact_email',254),('phone',40)]:
        op.add_column('stations',sa.Column(name,sa.String(length),nullable=False,server_default=''))
    op.add_column('stations',sa.Column('publish_contact',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_table('station_logos',
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('image',sa.LargeBinary(),nullable=False),sa.Column('thumbnail',sa.LargeBinary(),nullable=False),
        sa.Column('version',sa.String(64),nullable=False))
    op.create_table('song_flags',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('track_id',sa.Integer(),sa.ForeignKey('tracks.id',ondelete='CASCADE'),nullable=False),
        sa.Column('admin_user_id',sa.Integer(),sa.ForeignKey('admin_users.id',ondelete='SET NULL')),
        sa.Column('note',sa.String(2000),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('resolved_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('station_id','track_id',name='uq_song_flag_station_track'))
    op.create_index('ix_song_flags_station_id','song_flags',['station_id'])


def downgrade():
    op.drop_table('song_flags')
    op.drop_table('station_logos')
    with op.batch_alter_table('stations') as batch:
        for name in ('city','region','contact_email','phone','publish_contact'):
            batch.drop_column(name)
