"""Add worker-observed program level and merge operator modes.

Revision ID: d8a4b37f20ce
Revises: c2f6a7d91e40
"""
from alembic import op
import sqlalchemy as sa

revision='d8a4b37f20ce'
down_revision='c2f6a7d91e40'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('live_queue_snapshots', sa.Column('program_rms', sa.Float(), nullable=True))
    op.execute("UPDATE automation_states SET operator_mode='DJ_BOOTH', hold=true WHERE operator_mode IN ('LIVE','LIVE_ASSIST')")


def downgrade():
    op.execute("UPDATE automation_states SET operator_mode='LIVE_ASSIST' WHERE operator_mode='DJ_BOOTH'")
    op.drop_column('live_queue_snapshots','program_rms')
