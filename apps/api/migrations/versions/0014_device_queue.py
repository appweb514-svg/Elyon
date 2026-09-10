import sqlalchemy as sa
from alembic import op

revision = "0014_device_queue"
down_revision = "0013_playlist_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NB : 0001 crée le schéma courant via Base.metadata.create_all ; sur une
    # base neuve la colonne peut donc déjà exister — on ne l'ajoute que si
    # elle manque (idempotence), comme les migrations précédentes.
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("devices")}
    if "queue_json" not in cols:
        op.add_column(
            "devices",
            sa.Column("queue_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("devices", "queue_json")
