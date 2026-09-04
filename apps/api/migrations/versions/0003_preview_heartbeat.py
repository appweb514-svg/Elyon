import sqlalchemy as sa
from alembic import op

revision = "0003_preview_heartbeat"
down_revision = "0002_rbac_layout_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("devices")}
    with op.batch_alter_table("devices") as batch:
        if "player_state" not in cols:
            batch.add_column(sa.Column("player_state", sa.String(32), nullable=True))
        if "current_media_id" not in cols:
            batch.add_column(sa.Column("current_media_id", sa.String(32), nullable=True))
        if "is_preview" not in cols:
            batch.add_column(
                sa.Column("is_preview", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("is_preview")
        batch.drop_column("current_media_id")
        batch.drop_column("player_state")
