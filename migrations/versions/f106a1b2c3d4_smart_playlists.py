"""Phase 1 playlist leaders and dynamic selection configuration."""
from alembic import op
import sqlalchemy as sa
revision = 'f106a1b2c3d4'
down_revision = 'c83d4e5f9012'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('playlists') as batch:
        batch.add_column(sa.Column('leader_track_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_playlist_leader_track', 'tracks', ['leader_track_id'], ['id'], ondelete='SET NULL')
        batch.add_column(sa.Column('smart_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('smart_rules', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('selection_weights', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('selection_decisions', sa.Column('leader_key', sa.String(64), nullable=True))
    op.create_index('ix_selection_decisions_leader_key', 'selection_decisions', ['leader_key'])


def downgrade():
    op.drop_index('ix_selection_decisions_leader_key', table_name='selection_decisions')
    with op.batch_alter_table('selection_decisions') as batch:
        batch.drop_column('leader_key')
    with op.batch_alter_table('playlists') as batch:
        batch.drop_constraint('fk_playlist_leader_track', type_='foreignkey')
        for name in ('leader_track_id', 'smart_enabled', 'smart_rules', 'selection_weights'):
            batch.drop_column(name)
