"""Anonymous listener classifications and hourly observed session aggregates."""
from alembic import op
import sqlalchemy as sa

revision = 'f406a1b2c3d4'
down_revision = 'f316a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stats_presence', sa.Column('listening', sa.JSON(), nullable=True))
    op.create_table('stats_session_buckets',
        sa.Column('scope', sa.Integer(), primary_key=True),
        sa.Column('at', sa.BigInteger(), primary_key=True),
        sa.Column('data', sa.JSON(), nullable=False))
    op.create_index('ix_stats_session_buckets_at', 'stats_session_buckets', ['at'])


def downgrade():
    states = sa.table('stats_states', sa.column('scope', sa.Integer()), sa.column('data', sa.JSON()))
    connection = op.get_bind()
    for scope, data in connection.execute(sa.select(states.c.scope, states.c.data)).all():
        cleaned = {key: value for key, value in data.items() if key not in
                   ('sessions_since', 'session_clients_at', 'session_clients_valid')}
        if cleaned != data:
            connection.execute(states.update().where(states.c.scope == scope).values(data=cleaned))
    op.drop_table('stats_session_buckets')
    with op.batch_alter_table('stats_presence') as batch:
        batch.drop_column('listening')
