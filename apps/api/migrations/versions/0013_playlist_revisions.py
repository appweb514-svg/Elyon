import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0013_playlist_revisions"
down_revision = "0012_playlist_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "playlist_revisions" not in tables:
        op.create_table(
            "playlist_revisions",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "playlist_id",
                sa.String(32),
                sa.ForeignKey("playlists.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="published"),
            sa.Column("items_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column(
                "created_by",
                sa.String(32),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("playlist_id", "version", name="uq_playlist_revisions_version"),
        )
        op.create_index(
            "ix_playlist_revisions_playlist_created",
            "playlist_revisions",
            ["playlist_id", "created_at"],
        )

    columns = {column["name"] for column in sa.inspect(bind).get_columns("playlists")}
    if "published_revision_id" not in columns:
        with op.batch_alter_table("playlists") as batch:
            batch.add_column(sa.Column("published_revision_id", sa.String(32), nullable=True))

    playlists = bind.execute(sa.text("SELECT id FROM playlists")).mappings().all()
    for playlist in playlists:
        existing = bind.execute(
            sa.text(
                "SELECT id FROM playlist_revisions "
                "WHERE playlist_id = :playlist_id ORDER BY version DESC LIMIT 1"
            ),
            {"playlist_id": playlist["id"]},
        ).first()
        if existing is not None:
            continue
        items = bind.execute(
            sa.text(
                "SELECT id, media_id, position, duration_seconds FROM playlist_items "
                "WHERE playlist_id = :playlist_id ORDER BY position"
            ),
            {"playlist_id": playlist["id"]},
        ).mappings().all()
        revision_id = uuid.uuid4().hex
        bind.execute(
            sa.text(
                "INSERT INTO playlist_revisions "
                "(id, playlist_id, version, status, items_json, created_at) "
                "VALUES (:id, :playlist_id, 1, 'published', :items_json, CURRENT_TIMESTAMP)"
            ),
            {
                "id": revision_id,
                "playlist_id": playlist["id"],
                "items_json": json.dumps([dict(item) for item in items], separators=(",", ":")),
            },
        )
        bind.execute(
            sa.text(
                "UPDATE playlists SET published_revision_id = :revision_id WHERE id = :playlist_id"
            ),
            {"revision_id": revision_id, "playlist_id": playlist["id"]},
        )


def downgrade() -> None:
    with op.batch_alter_table("playlists") as batch:
        batch.drop_column("published_revision_id")
    op.drop_index("ix_playlist_revisions_playlist_created", table_name="playlist_revisions")
    op.drop_table("playlist_revisions")
