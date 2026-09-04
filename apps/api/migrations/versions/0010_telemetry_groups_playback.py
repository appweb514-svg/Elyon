import sqlalchemy as sa
from alembic import op

revision = "0010_telemetry_groups_playback"
down_revision = "0009_media_trash_office"
branch_labels = None
depends_on = None


def _cols(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    # Télémétrie device
    dcols = _cols(bind, "devices")
    with op.batch_alter_table("devices") as batch:
        for name, col in [
            ("uptime_seconds", sa.Integer()),
            ("load_avg", sa.Float()),
            ("memory_percent", sa.Float()),
            ("cpu_percent", sa.Float()),
            ("storage_free_bytes", sa.BigInteger()),
            ("lan_ip", sa.String(64)),
            ("wifi_ssid", sa.String(64)),
        ]:
            if name not in dcols:
                batch.add_column(sa.Column(name, col, nullable=True))

    # Groupes d'appareils
    if "device_groups" not in existing:
        op.create_table(
            "device_groups",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("org_id", sa.String(32), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("org_id", "name", name="uq_device_groups_org_name"),
        )
    if "device_group_members" not in existing:
        op.create_table(
            "device_group_members",
            sa.Column("group_id", sa.String(32), primary_key=True),
            sa.Column("device_id", sa.String(32), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["device_groups.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        )

    # Preuve de lecture (proof-of-play)
    if "playback_events" not in existing:
        op.create_table(
            "playback_events",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("org_id", sa.String(32), nullable=False),
            sa.Column("device_id", sa.String(32), nullable=False),
            sa.Column("media_id", sa.String(32), nullable=True),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_playback_device_recorded", "playback_events",
            ["device_id", "recorded_at"])
        op.create_index("ix_playback_org_recorded", "playback_events",
            ["org_id", "recorded_at"])


def downgrade() -> None:
    op.drop_table("playback_events")
    op.drop_table("device_group_members")
    op.drop_table("device_groups")
    with op.batch_alter_table("devices") as batch:
        for name in (
            "uptime_seconds", "load_avg", "memory_percent", "cpu_percent",
            "storage_free_bytes", "lan_ip", "wifi_ssid",
        ):
            batch.drop_column(name)
