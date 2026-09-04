import sqlalchemy as sa
from alembic import op

revision = "0004_media_user_owner"
down_revision = "0003_preview_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    media_cols = {c["name"] for c in inspector.get_columns("media")}
    if "user_id" not in media_cols:
        with op.batch_alter_table("media") as batch:
            batch.add_column(sa.Column("user_id", sa.String(32), nullable=True))
    existing_indexes = {i["name"] for i in inspector.get_indexes("media")}
    if "ix_media_user" not in existing_indexes:
        op.create_index("ix_media_user", "media", ["user_id"])

    # Backfill idempotent : chaque média sans propriétaire est rattaché à
    # l'admin (ou premier utilisateur actif) de son organisation.
    # `bind` est déjà la Connection SQLAlchemy retournée par op.get_bind().
    conn = bind
    orgs = [r[0] for r in conn.execute(sa.text("SELECT org_id FROM media GROUP BY org_id"))]
    for org_id in orgs:
        owner = conn.execute(
            sa.text(
                "SELECT id FROM users WHERE org_id = :org_id AND is_active "
                "ORDER BY CASE WHEN role = 'org_admin' THEN 0 ELSE 1 END, id LIMIT 1"
            ),
            {"org_id": org_id},
        ).scalar()
        if owner is None:
            continue
        conn.execute(
            sa.text(
                "UPDATE media SET user_id = :owner "
                "WHERE org_id = :org_id AND user_id IS NULL"
            ),
            {"owner": owner, "org_id": org_id},
        )


def downgrade() -> None:
    op.drop_index("ix_media_user", table_name="media")
    with op.batch_alter_table("media") as batch:
        batch.drop_column("user_id")
