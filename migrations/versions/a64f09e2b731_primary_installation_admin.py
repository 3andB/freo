"""Give the installer-created primary admin installation administration access."""
from alembic import op
import sqlalchemy as sa

revision = 'a64f09e2b731'
down_revision = 'f39c8210b7de'
branch_labels = None
depends_on = None


def upgrade():
    # Installer accounts retain this unique username after first-use setup.
    # Do not infer ownership from email, ID, activity or the number of accounts.
    users = sa.table('admin_users', sa.column('username', sa.String()),
                     sa.column('installation_admin', sa.Boolean()))
    op.execute(users.update().where(
        users.c.username == 'admin', users.c.installation_admin.is_(False)
    ).values(installation_admin=True))


def downgrade():
    # A previous explicit grant cannot be distinguished from this backfill.
    raise RuntimeError('Administrator permissions are durable state; use a matched recovery point.')
