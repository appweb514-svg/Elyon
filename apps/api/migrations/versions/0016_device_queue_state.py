import sqlalchemy as sa
from alembic import op

revision = "0016_device_queue_state"
down_revision = "0015_device_network"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """État d'auto-enchaînement de la file persisté sur le device.

    Idempotent : sur une base neuve, 0001 (create_all) a déjà créé les
    colonnes avec le schéma courant.
    """
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    with op.batch_alter_table("devices") as batch:
        if "queue_started_media_id" not in cols:
            batch.add_column(sa.Column("queue_started_media_id", sa.String(32), nullable=True))
        if "queue_started_at" not in cols:
            batch.add_column(
                sa.Column("queue_started_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "queue_stop_until" not in cols:
            batch.add_column(
                sa.Column("queue_stop_until", sa.DateTime(timezone=True), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("queue_stop_until")
        batch.drop_column("queue_started_at")
        batch.drop_column("queue_started_media_id")
