"""Station website drafts, atomic publications and immutable image assets."""
from alembic import op
import sqlalchemy as sa

revision = 'd91f3a26b807'
down_revision = 'c84a2e019b36'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('website_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('draft', sa.JSON(), nullable=False),
        sa.Column('published', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_website_singleton'))
    op.create_table('website_publications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('website_assets',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('image', sa.LargeBinary(), nullable=False),
        sa.Column('small', sa.LargeBinary(), nullable=False))


def downgrade():
    op.drop_table('website_assets')
    op.drop_table('website_publications')
    op.drop_table('website_settings')
