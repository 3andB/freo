"""Cart identity, programming checkpoints and broadcast observations."""
from alembic import op
import sqlalchemy as sa
revision='c48f1d207ab9'
down_revision='b27d903e1a46'
branch_labels=None
depends_on=None


def upgrade():
    for column in [sa.Column('cart_role',sa.String(8)),sa.Column('cart_position',sa.Integer()),
                   sa.Column('programming_signature',sa.String(64)),sa.Column('cursor_checkpoint',sa.JSON())]:
        op.add_column('selection_decisions',column)
    for column in [sa.Column('listeners',sa.Integer()),sa.Column('broadcast_online',sa.Boolean()),
                   sa.Column('broadcast_observed_at',sa.DateTime(timezone=True))]:
        op.add_column('live_queue_snapshots',column)


def downgrade():
    with op.batch_alter_table('live_queue_snapshots') as batch:
        for name in ('listeners','broadcast_online','broadcast_observed_at'):batch.drop_column(name)
    with op.batch_alter_table('selection_decisions') as batch:
        for name in ('cart_role','cart_position','programming_signature','cursor_checkpoint'):batch.drop_column(name)
