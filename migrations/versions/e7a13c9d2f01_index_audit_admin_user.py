"""Index audit events by administrator.

Revision ID: e7a13c9d2f01
Revises: d65fdad18060
"""
from alembic import op

revision = 'e7a13c9d2f01'
down_revision = 'd65fdad18060'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_audit_events_admin_user_id', 'audit_events', ['admin_user_id'])


def downgrade():
    op.drop_index('ix_audit_events_admin_user_id', table_name='audit_events')
