"""Add the persistent DJ cue deck and fade control action.

Revision ID: c2f6a7d91e40
Revises: a8d1e4f72c10
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2f6a7d91e40'
down_revision = 'a8d1e4f72c10'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('automation_states', sa.Column('cued_track_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_automation_state_cued_track', 'automation_states',
        'tracks', ['cued_track_id'], ['id'], ondelete='SET NULL')
    op.drop_constraint('ck_live_control_action', 'live_control_commands', type_='check')
    op.create_check_constraint('ck_live_control_action', 'live_control_commands',
        "action IN ('SKIP','TAKEOVER','FADE')")


def downgrade():
    op.drop_constraint('ck_live_control_action', 'live_control_commands', type_='check')
    op.create_check_constraint('ck_live_control_action', 'live_control_commands',
        "action IN ('SKIP','TAKEOVER')")
    op.drop_constraint('fk_automation_state_cued_track', 'automation_states', type_='foreignkey')
    op.drop_column('automation_states', 'cued_track_id')
