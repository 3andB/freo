"""Station listener requests and durable selection bindings."""
from alembic import op
import sqlalchemy as sa

revision = 'f506a1b2c3d4'
down_revision = 'f406a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('request_settings', sa.JSON(), nullable=False, server_default='{}'))
    op.create_table('listener_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('track_id', sa.Integer(), sa.ForeignKey('tracks.id', ondelete='SET NULL')),
        sa.Column('listener_key', sa.String(64)), sa.Column('nonce', sa.String(36)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('played_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('reason', sa.String(160), nullable=False), sa.Column('evidence', sa.JSON()),
        sa.CheckConstraint("status IN ('pending','eligible','queued','played','rejected','expired')", name='ck_listener_request_status'),
        sa.UniqueConstraint('station_id', 'listener_key', 'nonce', name='uq_listener_request_nonce'))
    op.create_index('ix_listener_requests_station_status_created', 'listener_requests', ['station_id', 'status', 'created_at'])
    op.create_table('request_rate_buckets',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('key', sa.String(64), primary_key=True), sa.Column('kind', sa.String(12), primary_key=True),
        sa.Column('minute', sa.BigInteger(), primary_key=True), sa.Column('count', sa.Integer(), nullable=False))
    with op.batch_alter_table('selection_decisions') as batch:
        batch.add_column(sa.Column('listener_request_id', sa.Integer()))
        batch.create_foreign_key('fk_decision_listener_request', 'listener_requests', ['listener_request_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_selection_decisions_listener_request_id', ['listener_request_id'])


def downgrade():
    with op.batch_alter_table('selection_decisions') as batch:
        batch.drop_index('ix_selection_decisions_listener_request_id')
        batch.drop_constraint('fk_decision_listener_request', type_='foreignkey')
        batch.drop_column('listener_request_id')
    op.drop_table('request_rate_buckets')
    op.drop_table('listener_requests')
    op.drop_column('stations', 'request_settings')
