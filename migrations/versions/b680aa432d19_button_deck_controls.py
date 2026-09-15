"""Durable deck-specific button commands."""
from alembic import op
import sqlalchemy as sa
revision='b680aa432d19'
down_revision='a57ce920bd31'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('live_control_commands') as batch:
        batch.add_column(sa.Column('deck',sa.String(1),nullable=True))
        batch.drop_constraint('ck_live_control_action',type_='check')
        batch.create_check_constraint('ck_live_control_action',"action IN ('SKIP','TAKEOVER','FADE','DECK_LOAD','DECK_PLAY','DECK_PAUSE','DECK_CLEAR','DECK_FADE','DECK_REPEAT')")

def downgrade():
    op.execute("DELETE FROM live_control_commands WHERE action LIKE 'DECK_%'")
    with op.batch_alter_table('live_control_commands') as batch:
        batch.drop_constraint('ck_live_control_action',type_='check')
        batch.create_check_constraint('ck_live_control_action',"action IN ('SKIP','TAKEOVER','FADE')")
        batch.drop_column('deck')
