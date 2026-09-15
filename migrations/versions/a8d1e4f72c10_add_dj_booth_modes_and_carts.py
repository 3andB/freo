"""Add DJ booth modes, fixed cart positions, and takeover intents.

Revision ID: a8d1e4f72c10
Revises: f4c2d8a91b30
"""
from alembic import op
import sqlalchemy as sa
revision='a8d1e4f72c10';down_revision='f4c2d8a91b30';branch_labels=None;depends_on=None
def upgrade():
    op.add_column('automation_states',sa.Column('operator_mode',sa.String(16),nullable=False,server_default='AUTO'))
    op.add_column('live_control_commands',sa.Column('target_decision_id',sa.Integer(),sa.ForeignKey('selection_decisions.id',ondelete='SET NULL')))
    op.add_column('live_control_commands',sa.Column('action',sa.String(12),nullable=False,server_default='SKIP'))
    op.create_check_constraint('ck_live_control_action','live_control_commands',"action IN ('SKIP','TAKEOVER')")
    op.create_table('live_cart_slots',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('station_id',sa.Integer(),sa.ForeignKey('stations.id',ondelete='CASCADE'),nullable=False),sa.Column('role',sa.String(4),nullable=False),sa.Column('position',sa.Integer(),nullable=False),sa.Column('imaging_asset_id',sa.Integer(),sa.ForeignKey('imaging_assets.id',ondelete='SET NULL')),sa.Column('label',sa.String(40),nullable=False,server_default=''),sa.UniqueConstraint('station_id','role','position',name='uq_live_cart_station_role_position'),sa.CheckConstraint("role IN ('HOT','ID')",name='ck_live_cart_role'),sa.CheckConstraint("(role='HOT' AND position BETWEEN 1 AND 8) OR (role='ID' AND position BETWEEN 1 AND 4)",name='ck_live_cart_position'))
    op.create_index('ix_live_cart_slots_station_id','live_cart_slots',['station_id'])
def downgrade():
    op.drop_table('live_cart_slots');op.drop_constraint('ck_live_control_action','live_control_commands',type_='check');op.drop_column('live_control_commands','action');op.drop_column('live_control_commands','target_decision_id');op.drop_column('automation_states','operator_mode')
