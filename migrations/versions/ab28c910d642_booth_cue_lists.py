"""Persistent booth Cue lists and playback completion identity."""
from alembic import op
import sqlalchemy as sa

revision = 'ab28c910d642'
down_revision = 'f19a73b206ce'
branch_labels = None
depends_on = None


def upgrade():
    station = lambda: sa.Column('station_id', sa.Integer(), sa.ForeignKey('stations.id', ondelete='CASCADE'), nullable=False)
    op.create_table('booth_cues', station(),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('generation', sa.String(36), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('entries', sa.JSON(), nullable=False),
        sa.Column('saved_id', sa.Integer()),
        sa.Column('saved_order', sa.JSON(), nullable=False),
        sa.Column('auto_enabled', sa.Boolean(), nullable=False),
        sa.Column('start_pending', sa.Boolean(), nullable=False),
        sa.Column('last_deck', sa.String(1), nullable=False),
        sa.Column('message', sa.String(240), nullable=False),
        sa.PrimaryKeyConstraint('station_id'))
    op.create_table('saved_booth_cues', sa.Column('id', sa.Integer(), primary_key=True), station(),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('tracks', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('cue_playbacks',
        sa.Column('decision_id', sa.Integer(), sa.ForeignKey('selection_decisions.id', ondelete='CASCADE'), primary_key=True), station(),
        sa.Column('generation', sa.String(36), nullable=False),
        sa.Column('entry_id', sa.String(36)),
        sa.Column('interrupted', sa.Boolean(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)))
    op.create_table('cue_mutations', sa.Column('token', sa.String(36), primary_key=True), station(),
        sa.Column('fingerprint', sa.String(64), nullable=False))
    for table in ('saved_booth_cues', 'cue_playbacks', 'cue_mutations'):
        op.create_index('ix_'+table+'_station_id', table, ['station_id'])


def downgrade():
    for table in ('cue_mutations', 'cue_playbacks', 'saved_booth_cues', 'booth_cues'):
        op.drop_table(table)
