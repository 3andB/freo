"""Retain observation provenance without rewriting historical reporting rows."""
from alembic import op
import sqlalchemy as sa

revision = 'fd17b2c3d4e5'
down_revision = 'fc06a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('central_hourly_metrics', sa.Column('coverage', sa.JSON(), nullable=True))


def downgrade():
    # Removing provenance would erase known coverage and compromise replacement
    # receipts. Application rollback uses the matched, verified recovery point.
    raise RuntimeError('Restore the matched recovery point; reporting provenance must not be discarded')
