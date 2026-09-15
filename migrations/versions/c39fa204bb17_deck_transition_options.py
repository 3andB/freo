"""Carry confirmed deck replacement and fade duration to the audio worker."""
from alembic import op
import sqlalchemy as sa

revision = 'c39fa204bb17'
down_revision = 'b680aa432d19'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('live_control_commands') as batch:
        batch.add_column(sa.Column('fade_seconds', sa.Float(), nullable=False, server_default='3'))
        batch.add_column(sa.Column('play_on_load', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('live_control_commands') as batch:
        batch.drop_column('play_on_load')
        batch.drop_column('fade_seconds')
