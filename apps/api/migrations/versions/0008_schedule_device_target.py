import sqlalchemy as sa
from alembic import op

revision = "0008_schedule_device_target"
down_revision = "0007_screen_widgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("schedules")}
    if "device_id" not in cols:
        with op.batch_alter_table("schedules") as batch:
            batch.add_column(sa.Column("device_id", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_column("device_id")
