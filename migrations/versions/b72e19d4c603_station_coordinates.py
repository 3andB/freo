"""Optional approximate coordinates for the configured station location."""
from alembic import op
import sqlalchemy as sa

revision = 'b72e19d4c603'
down_revision = 'a64f09e2b731'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('stations', sa.Column('longitude', sa.Float(), nullable=True))
    op.create_check_constraint('ck_stations_coordinates', 'stations',
        '(latitude IS NULL AND longitude IS NULL) OR '
        '(latitude IS NOT NULL AND longitude IS NOT NULL AND '
        'latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)')


def downgrade():
    raise RuntimeError('Station locations are durable state; use a matched recovery point.')
