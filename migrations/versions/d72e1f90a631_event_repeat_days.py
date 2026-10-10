"""Multi-day event recurrence with one stable event identity."""
from alembic import op
import sqlalchemy as sa

revision = 'd72e1f90a631'
down_revision = 'c39fa204bb17'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schedule_programs') as batch:
        batch.add_column(sa.Column('baseline_assignment_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_program_baseline_assignment', 'schedule_assignments', ['baseline_assignment_id'], ['id'], ondelete='RESTRICT')
    op.add_column('timed_events', sa.Column('weekdays', sa.String(20), nullable=True))


def downgrade():
    # Multi-day series need explicit conversion before an older worker can run.
    connection = op.get_bind()
    count = connection.execute(sa.text("SELECT count(*) FROM timed_events WHERE weekdays LIKE '%,%' AND enabled = true")).scalar()
    if count:
        raise RuntimeError('Disable or convert multi-day events before downgrading')
    converted = connection.execute(sa.text('SELECT count(*) FROM schedule_programs WHERE baseline_assignment_id IS NOT NULL AND enabled = true')).scalar()
    if converted:
        raise RuntimeError('Restore converted weekly assignments before downgrading')
    with op.batch_alter_table('schedule_programs') as batch:
        batch.drop_constraint('fk_program_baseline_assignment', type_='foreignkey')
        batch.drop_column('baseline_assignment_id')
    op.drop_column('timed_events', 'weekdays')
