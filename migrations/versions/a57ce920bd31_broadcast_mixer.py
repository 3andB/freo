"""Independent broadcast decks and shared song/imaging carts."""
from alembic import op
import sqlalchemy as sa
revision='a57ce920bd31'
down_revision='f35a908ed421'
branch_labels=None
depends_on=None


def upgrade():
    for column in [sa.Column('crossfader',sa.Float(),nullable=False,server_default='0'),sa.Column('deck_a_playing',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('deck_b_playing',sa.Boolean(),nullable=False,server_default=sa.false())]:
        op.add_column('automation_states',column)
    for column in [sa.Column('playback_bus',sa.String(8),nullable=False,server_default='A'),sa.Column('cart_mode',sa.String(8),nullable=False,server_default='OVER'),sa.Column('duck_percent',sa.Integer(),nullable=False,server_default='50')]:
        op.add_column('selection_decisions',column)
    op.add_column('live_queue_snapshots',sa.Column('mixer',sa.JSON()))
    with op.batch_alter_table('live_cart_slots') as batch:
        batch.add_column(sa.Column('track_id',sa.Integer()))
        batch.create_foreign_key('fk_live_cart_track','tracks',['track_id'],['id'],ondelete='SET NULL')
        batch.add_column(sa.Column('description',sa.String(500),nullable=False,server_default=''))
        batch.add_column(sa.Column('playback_mode',sa.String(8),nullable=False,server_default='OVER'))
        batch.add_column(sa.Column('duck_percent',sa.Integer(),nullable=False,server_default='50'))


def downgrade():
    with op.batch_alter_table('live_cart_slots') as batch:
        batch.drop_constraint('fk_live_cart_track',type_='foreignkey')
        for name in ('track_id','description','playback_mode','duck_percent'):batch.drop_column(name)
    op.drop_column('live_queue_snapshots','mixer')
    for name in ('playback_bus','cart_mode','duck_percent'):op.drop_column('selection_decisions',name)
    for name in ('crossfader','deck_a_playing','deck_b_playing'):op.drop_column('automation_states',name)
