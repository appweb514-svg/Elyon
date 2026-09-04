import sqlalchemy as sa
from alembic import op

revision = "0011_schedule_exclusions"
down_revision = "0010_telemetry_groups_playback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "schedule_exclusions" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "schedule_exclusions",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("schedule_id", sa.String(32), nullable=False),
            sa.Column("device_id", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("schedule_id", "device_id", name="uq_exclusion_schedule_device"),
            sa.Index("ix_exclusions_device", "device_id"),
        )


def downgrade() -> None:
    op.drop_table("schedule_exclusions")
