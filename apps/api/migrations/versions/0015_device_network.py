import sqlalchemy as sa
from alembic import op

revision = "0015_device_network"
down_revision = "0014_device_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("network_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "network_json")
