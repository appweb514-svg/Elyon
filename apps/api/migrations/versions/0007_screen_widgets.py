import sqlalchemy as sa
from alembic import op

revision = "0007_screen_widgets"
down_revision = "0006_teams_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("screens")}
    if "widgets_json" not in cols:
        with op.batch_alter_table("screens") as batch:
            batch.add_column(sa.Column("widgets_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("screens") as batch:
        batch.drop_column("widgets_json")
