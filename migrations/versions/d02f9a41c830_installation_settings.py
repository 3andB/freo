"""Durable installation settings; import host values explicitly after migration."""
from alembic import op
import sqlalchemy as sa

revision = 'd02f9a41c830'
down_revision = 'a71d25b609ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('installation_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_installation_settings_singleton'),
        sa.CheckConstraint('revision > 0', name='ck_installation_settings_revision'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM installation_settings')).scalar():
        raise RuntimeError('Installation settings are populated; restore a matched backup instead of dropping settings')
    op.drop_table('installation_settings')
