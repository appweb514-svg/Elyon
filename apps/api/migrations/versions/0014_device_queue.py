import sqlalchemy as sa
from alembic import op

revision = "0014_device_queue"
down_revision = "0013_playlist_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("queue_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "queue_json")
