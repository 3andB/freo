"""Durable local audience, geography, storage and feedback analytics."""
from alembic import op
import sqlalchemy as sa

revision = 'b185c9a027d6'
down_revision = 'ab92e51c7034'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index('ix_decision_stats_started', 'selection_decisions', ['status', 'started_at', 'station_id'])
    op.create_table('stats_buckets',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('resolution', sa.String(length=12), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('observed_seconds', sa.Float(), nullable=False),
    sa.Column('listener_seconds', sa.Float(), nullable=False),
    sa.Column('online_seconds', sa.Float(), nullable=False),
    sa.Column('peak', sa.Integer(), nullable=False),
    sa.Column('bytes_sent', sa.BigInteger(), nullable=False),
    sa.Column('transfer_seconds', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'resolution', 'at')
    )
    op.create_index(op.f('ix_stats_buckets_at'), 'stats_buckets', ['at'], unique=False)
    op.create_table('stats_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('track_id', sa.Integer(), nullable=False),
    sa.Column('vote_id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('old_value', sa.Integer(), nullable=False),
    sa.Column('new_value', sa.Integer(), nullable=False),
    sa.Column('old_excluded', sa.Boolean(), nullable=False),
    sa.Column('new_excluded', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vote_id', 'revision', name='uq_stats_feedback_revision')
    )
    op.create_index(op.f('ix_stats_feedback_at'), 'stats_feedback', ['at'], unique=False)
    op.create_index(op.f('ix_stats_feedback_scope'), 'stats_feedback', ['scope'], unique=False)
    op.create_index(op.f('ix_stats_feedback_track_id'), 'stats_feedback', ['track_id'], unique=False)
    op.create_table('stats_geo_buckets',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=12), nullable=False),
    sa.Column('place', sa.String(length=64), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('geo', sa.JSON(), nullable=False),
    sa.Column('sessions', sa.Integer(), nullable=False),
    sa.Column('observed_seconds', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'source', 'place', 'at')
    )
    op.create_index(op.f('ix_stats_geo_buckets_at'), 'stats_geo_buckets', ['at'], unique=False)
    op.create_table('stats_geo_reach',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=12), nullable=False),
    sa.Column('place', sa.String(length=64), nullable=False),
    sa.Column('geo', sa.JSON(), nullable=False),
    sa.Column('first_seen', sa.BigInteger(), nullable=False),
    sa.Column('last_seen', sa.BigInteger(), nullable=False),
    sa.Column('sessions', sa.BigInteger(), nullable=False),
    sa.Column('observed_seconds', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'source', 'place')
    )
    op.create_table('stats_incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.BigInteger(), nullable=False),
    sa.Column('ended_at', sa.BigInteger(), nullable=True),
    sa.Column('detail', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stats_incidents_scope'), 'stats_incidents', ['scope'], unique=False)
    op.create_index(op.f('ix_stats_incidents_started_at'), 'stats_incidents', ['started_at'], unique=False)
    op.create_table('stats_presence',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=12), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('first_seen', sa.BigInteger(), nullable=False),
    sa.Column('last_seen', sa.BigInteger(), nullable=False),
    sa.Column('geo', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'source', 'key')
    )
    op.create_index(op.f('ix_stats_presence_last_seen'), 'stats_presence', ['last_seen'], unique=False)
    op.create_table('stats_samples',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('listeners', sa.Integer(), nullable=True),
    sa.Column('online', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('scope', 'at')
    )
    op.create_index(op.f('ix_stats_samples_at'), 'stats_samples', ['at'], unique=False)
    op.create_table('stats_states',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('scope')
    )
    op.create_table('stats_storage',
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('scope', 'at')
    )
    op.create_index(op.f('ix_stats_storage_at'), 'stats_storage', ['at'], unique=False)

def downgrade():
    op.drop_index('ix_decision_stats_started', table_name='selection_decisions')
    op.drop_index(op.f('ix_stats_storage_at'), table_name='stats_storage')
    op.drop_table('stats_storage')
    op.drop_table('stats_states')
    op.drop_index(op.f('ix_stats_samples_at'), table_name='stats_samples')
    op.drop_table('stats_samples')
    op.drop_index(op.f('ix_stats_presence_last_seen'), table_name='stats_presence')
    op.drop_table('stats_presence')
    op.drop_index(op.f('ix_stats_incidents_started_at'), table_name='stats_incidents')
    op.drop_index(op.f('ix_stats_incidents_scope'), table_name='stats_incidents')
    op.drop_table('stats_incidents')
    op.drop_table('stats_geo_reach')
    op.drop_index(op.f('ix_stats_geo_buckets_at'), table_name='stats_geo_buckets')
    op.drop_table('stats_geo_buckets')
    op.drop_index(op.f('ix_stats_feedback_track_id'), table_name='stats_feedback')
    op.drop_index(op.f('ix_stats_feedback_scope'), table_name='stats_feedback')
    op.drop_index(op.f('ix_stats_feedback_at'), table_name='stats_feedback')
    op.drop_table('stats_feedback')
    op.drop_index(op.f('ix_stats_buckets_at'), table_name='stats_buckets')
    op.drop_table('stats_buckets')
