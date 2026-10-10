"""Station lifecycle and inherited library availability.

Retain station identities as media storage owners after runtime deletion.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ea640b19c275'
down_revision = 'f61c20d9a843'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('deleted_at', sa.DateTime(timezone=True)))
    op.create_index('ix_stations_deleted_at', 'stations', ['deleted_at'])
    op.add_column('stations', sa.Column('lifecycle_state', sa.String(24), nullable=False, server_default='ready'))
    op.add_column('stations', sa.Column('lifecycle_error', sa.String(500), nullable=False, server_default=''))
    for table in ('artists', 'albums', 'tracks'):
        op.add_column(table, sa.Column('available_to_all', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM stations WHERE deleted_at IS NOT NULL OR lifecycle_state != 'ready'")).scalar():
        raise RuntimeError('Resolve pending operations and retained deleted stations before downgrading')
    if connection.execute(sa.text('SELECT count(*) FROM tracks WHERE available_to_all')).scalar() or any(
        connection.execute(sa.text(f'SELECT count(*) FROM {table} WHERE available_to_all')).scalar()
        for table in ('artists', 'albums')
    ):
        raise RuntimeError('Remove shared-library dependencies before downgrading')
    for table in ('artists', 'albums', 'tracks'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('available_to_all')
    with op.batch_alter_table('stations') as batch:
        batch.drop_index('ix_stations_deleted_at')
        batch.drop_column('deleted_at')
        batch.drop_column('lifecycle_state')
        batch.drop_column('lifecycle_error')
