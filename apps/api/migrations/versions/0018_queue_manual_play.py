import sqlalchemy as sa
from alembic import op

revision = "0018_queue_manual_play"
down_revision = "0017_device_pause_page"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    if "queue_auto_advance" not in cols:
        op.add_column(
            "devices",
            sa.Column(
                "queue_auto_advance",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    op.drop_column("devices", "queue_auto_advance")
