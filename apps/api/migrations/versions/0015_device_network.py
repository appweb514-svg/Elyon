import sqlalchemy as sa
from alembic import op

revision = "0015_device_network"
down_revision = "0014_device_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent : sur une base neuve, 0001 (create_all) a déjà créé la
    # colonne avec le schéma courant.
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    if "network_json" not in cols:
        op.add_column(
            "devices",
            sa.Column("network_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("devices", "network_json")
