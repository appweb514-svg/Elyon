import sqlalchemy as sa
from alembic import op

revision = "0006_teams_profile"
down_revision = "0004_media_user_owner"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "teams" not in existing:
        op.create_table(
            "teams",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("org_id", sa.String(32), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("quota_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("org_id", "name", name="uq_teams_org_name"),
        )

    user_cols = _columns(bind, "users")
    with op.batch_alter_table("users") as batch:
        if "team_id" not in user_cols:
            batch.add_column(sa.Column("team_id", sa.String(32), nullable=True))
        if "quota_bytes" not in user_cols:
            batch.add_column(
                sa.Column("quota_bytes", sa.BigInteger(), nullable=False, server_default="0")
            )

    media_cols = _columns(bind, "media")
    with op.batch_alter_table("media") as batch:
        if "team_id" not in media_cols:
            batch.add_column(sa.Column("team_id", sa.String(32), nullable=True))
    media_indexes = {i["name"] for i in sa.inspect(bind).get_indexes("media")}
    if "ix_media_team" not in media_indexes:
        op.create_index("ix_media_team", "media", ["team_id"])

    # Les FK sur users.team_id et media.team_id : ajoutées si absentes.
    fks_users = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("users")}
    if "fk_users_team" not in fks_users:
        with op.batch_alter_table("users", schema=None) as batch:
            batch.create_foreign_key(
                "fk_users_team", "teams", ["team_id"], ["id"], ondelete="SET NULL"
            )
    fks_media = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("media")}
    if "fk_media_team" not in fks_media:
        with op.batch_alter_table("media", schema=None) as batch:
            batch.create_foreign_key(
                "fk_media_team", "teams", ["team_id"], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    with op.batch_alter_table("media", schema=None) as batch:
        batch.drop_constraint("fk_media_team", type_="foreignkey")
        batch.drop_column("team_id")
    op.drop_index("ix_media_team", table_name="media")
    with op.batch_alter_table("users", schema=None) as batch:
        batch.drop_constraint("fk_users_team", type_="foreignkey")
        batch.drop_column("team_id")
        batch.drop_column("quota_bytes")
    op.drop_table("teams")
