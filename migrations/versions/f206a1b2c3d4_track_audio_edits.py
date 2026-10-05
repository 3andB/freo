"""Opt-in non-destructive track audio edits."""
from alembic import op
import sqlalchemy as sa

revision = 'f206a1b2c3d4'
down_revision = 'f106a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tracks') as batch:
        batch.add_column(sa.Column('audio_edit_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('audio_edit_revision', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('fade_in_ms', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('fade_out_ms', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('gain_trim_db', sa.Float(), nullable=True))
    op.add_column('selection_decisions', sa.Column('audio_snapshot', sa.JSON(), nullable=True))
    op.add_column('event_block_item_executions', sa.Column('audio_snapshot', sa.JSON(), nullable=True))


def downgrade():
    for table in ('selection_decisions', 'event_block_item_executions'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('audio_snapshot')
    with op.batch_alter_table('tracks') as batch:
        for name in ('gain_trim_db', 'fade_out_ms', 'fade_in_ms', 'audio_edit_revision', 'audio_edit_enabled'):
            batch.drop_column(name)
