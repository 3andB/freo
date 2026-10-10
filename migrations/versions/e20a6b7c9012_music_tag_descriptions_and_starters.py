"""Add descriptions and seed the seven editable starter tags once."""
from alembic import op
import sqlalchemy as sa

revision = 'e20a6b7c9012'
down_revision = 'd72e1f90a631'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('music_tags', sa.Column('description', sa.String(500), nullable=False, server_default=''))
    connection = op.get_bind()
    tags = sa.table('music_tags', sa.column('station_id', sa.Integer), sa.column('name', sa.String),
                    sa.column('slug', sa.String), sa.column('color', sa.String), sa.column('description', sa.String))
    for station_id in connection.execute(sa.text('SELECT id FROM stations')).scalars():
        existing = set(connection.execute(sa.select(tags.c.slug).where(tags.c.station_id == station_id)).scalars())
        for name in ('HIT', 'FAVORITE', 'SPONSORED', 'CHILL', 'NIGHT', 'DAY', 'DANCE'):
            if name.lower() not in existing:
                connection.execute(tags.insert().values(station_id=station_id, name=name, slug=name.lower(), color='#b9e79b', description=''))


def downgrade():
    # Keep tags and song assignments: users may have edited the starter tags.
    with op.batch_alter_table('music_tags') as batch:
        batch.drop_column('description')
