import sqlalchemy as sa
from alembic import op

revision = "0009_media_trash_office"
down_revision = "0008_schedule_device_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("media")}
    if "deleted_at" not in cols:
        with op.batch_alter_table("media") as batch:
            batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media") as batch:
        batch.drop_column("deleted_at")
