"""Default public listing on while retaining evidence of legacy opt-outs."""
from alembic import op
import sqlalchemy as sa

revision = 'fe28c3d4e5f6'
down_revision = 'fd17b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('stations', sa.Column('directory_consent_source', sa.String(32),
                                      nullable=False, server_default='default_on'))
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE stations SET directory_consent_source = CASE
          WHEN directory_opt_in THEN 'legacy_on'
          WHEN EXISTS (SELECT 1 FROM audit_events a
                       WHERE a.station_id = stations.id AND a.action = 'station_details_updated')
            THEN 'legacy_preserved_off'
          ELSE 'migrated_default_on' END
    """))
    connection.execute(sa.text("UPDATE stations SET directory_opt_in = true "
                               "WHERE directory_consent_source = 'migrated_default_on'"))
    with op.batch_alter_table('stations') as batch:
        batch.alter_column('directory_opt_in', existing_type=sa.Boolean(),
                           existing_nullable=False, server_default=sa.true())
    # Digests must be acknowledged anew, including migrated public consent.
    connection.execute(sa.text('UPDATE central_station_state SET synced_digest = NULL'))


def downgrade():
    raise RuntimeError('Restore the matched recovery point; retain public consent provenance')
