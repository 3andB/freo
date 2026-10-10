"""Durable operator-requested mothership connection checks."""
from alembic import op
import sqlalchemy as sa

revision = 'ab31e76f209d'
down_revision = 'd91f3a26b807'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('central_connection_check',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('requested_at', sa.Float(), nullable=False),
        sa.Column('started_at', sa.Float()),
        sa.Column('finished_at', sa.Float()),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_central_connection_check_singleton'))


def downgrade():
    op.drop_table('central_connection_check')
