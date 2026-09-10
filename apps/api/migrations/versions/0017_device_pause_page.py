import sqlalchemy as sa
from alembic import op

revision = "0017_device_pause_page"
down_revision = "0016_device_queue_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Page en cours (PDF/Office) et gel d'affichage (pause).

    Idempotent : sur une base neuve, 0001 (create_all) a déjà créé les colonnes.
    """
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    with op.batch_alter_table("devices") as batch:
        if "current_page_index" not in cols:
            batch.add_column(sa.Column("current_page_index", sa.Integer(), nullable=True))
        if "is_paused" not in cols:
            batch.add_column(
                sa.Column(
                    "is_paused",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("is_paused")
        batch.drop_column("current_page_index")
