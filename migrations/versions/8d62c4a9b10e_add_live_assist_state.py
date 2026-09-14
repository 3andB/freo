"""Add held automation and worker-mediated manual controls.

Revision ID: 8d62c4a9b10e
Revises: 4a97b6c1d2e3
"""
from alembic import op
import sqlalchemy as sa

revision = '8d62c4a9b10e'
down_revision = '4a97b6c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('automation_states', sa.Column('hold', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('selection_decisions', sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')))
    op.add_column('selection_decisions', sa.Column('idempotency_key', sa.String(36)))
    op.create_unique_constraint('uq_decision_idempotency_key', 'selection_decisions', ['idempotency_key'])
    op.drop_constraint('ck_decision_status', 'selection_decisions', type_='check')
    op.create_check_constraint('ck_decision_status', 'selection_decisions', "status IN ('selected','submitting','queued','started','failed')")
    op.create_table('live_control_commands',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL')),
        sa.Column('idempotency_key', sa.String(36), nullable=False, unique=True),
        sa.Column('expected_decision_id', sa.Integer(), sa.ForeignKey('selection_decisions.id', ondelete='SET NULL')),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True)),
        sa.Column('error_code', sa.String(40)),
        sa.CheckConstraint("status IN ('pending','sent','failed')", name='ck_live_control_status'))
    op.create_index('ix_live_control_commands_station_id', 'live_control_commands', ['station_id'])
    op.create_table('live_queue_snapshots',
        sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('current_decision_id', sa.Integer()),
        sa.Column('queued_decision_ids', sa.JSON(), nullable=False),
        sa.Column('unknown_count', sa.Integer(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('error_code', sa.String(40)))


def downgrade():
    op.drop_table('live_queue_snapshots')
    op.drop_table('live_control_commands')
    op.drop_constraint('ck_decision_status', 'selection_decisions', type_='check')
    op.create_check_constraint('ck_decision_status', 'selection_decisions', "status IN ('selected','queued','started','failed')")
    op.drop_constraint('uq_decision_idempotency_key', 'selection_decisions', type_='unique')
    op.drop_column('selection_decisions', 'idempotency_key')
    op.drop_column('selection_decisions', 'admin_user_id')
    op.drop_column('automation_states', 'hold')
