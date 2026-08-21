import sqlalchemy as sa
from alembic import op

revision = "0002_rbac_layout_status"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # users.site_id (FK sites.id, nullable, SET NULL)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "site_id" not in cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("site_id", sa.String(32), nullable=True))
            batch.create_foreign_key(
                "fk_users_site_id", "sites", ["site_id"], ["id"], ondelete="SET NULL"
            )
    # screens.layout_json
    scols = {c["name"] for c in inspector.get_columns("screens")}
    if "layout_json" not in scols:
        with op.batch_alter_table("screens") as batch:
            batch.add_column(sa.Column("layout_json", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("screens") as b:
        b.drop_column("layout_json")
    with op.batch_alter_table("users") as b:
        try:
            b.drop_constraint("fk_users_site_id", type_="foreignkey")
        except Exception:
            pass
        b.drop_column("site_id")
