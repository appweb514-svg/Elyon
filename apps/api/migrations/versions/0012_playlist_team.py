import sqlalchemy as sa
from alembic import op

revision = "0012_playlist_team"
down_revision = "0011_schedule_exclusions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("playlists")}
    if "team_id" not in cols:
        # NULL = playliste globale (historique / créée par un administrateur).
        with op.batch_alter_table("playlists") as batch:
            batch.add_column(sa.Column("team_id", sa.String(32), nullable=True))
            batch.create_foreign_key(
                "fk_playlists_team", "teams", ["team_id"], ["id"], ondelete="SET NULL"
            )
        # create_index en dehors du batch : la forme « batch » décompose une
        # chaîne colonne en caractères (doit être une liste).
        op.create_index("ix_playlists_team", "playlists", ["team_id"])


def downgrade() -> None:
    with op.batch_alter_table("playlists") as batch:
        batch.drop_index("ix_playlists_team")
        batch.drop_constraint("fk_playlists_team", type_="foreignkey")
        batch.drop_column("team_id")
