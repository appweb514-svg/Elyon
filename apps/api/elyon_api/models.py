from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _enum(t, length: int = 32) -> Enum:
    return Enum(t, native_enum=False, length=length)


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    SUPERADMIN = "superadmin"
    ORG_ADMIN = "org_admin"
    SITE_MANAGER = "site_manager"
    OPERATOR = "operator"
    VIEWER = "viewer"


class DeviceStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    BLOCKED = "blocked"


class MediaKind(enum.StrEnum):
    VIDEO = "video"
    IMAGE = "image"
    PDF = "pdf"


class MediaStatus(enum.StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class CommandStatus(enum.StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKED = "acked"
    FAILED = "failed"


class CommandType(enum.StrEnum):
    REBOOT = "reboot"
    RESYNC = "resync"
    BLANK = "blank"
    UNBLANK = "unblank"
    CAPTURE = "capture"


class EventLevel(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    quota_bytes: Mapped[int] = mapped_column(BigInteger, default=20 * 1024**3)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    users: Mapped[list[User]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    organization: Mapped[Organization | None] = relationship(back_populates="users")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_sites_org_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Paris")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    organization: Mapped[Organization] = relationship()
    screens: Mapped[list[Screen]] = relationship(back_populates="site")
    devices: Mapped[list[Device]] = relationship(back_populates="site")
    schedules: Mapped[list[Schedule]] = relationship(back_populates="site")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_org_status", "org_id", "status"),
        Index("ix_devices_last_seen", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    site_id: Mapped[str | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    serial: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[DeviceStatus] = mapped_column(_enum(DeviceStatus), default=DeviceStatus.PENDING)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_token_created_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auth_token_revoked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    site: Mapped[Site | None] = relationship(back_populates="devices")
    screen: Mapped[Screen | None] = relationship(back_populates="device")


class Screen(Base):
    __tablename__ = "screens"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_screens_site_name"),
        UniqueConstraint("device_id", name="uq_screens_device"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    width: Mapped[int] = mapped_column(Integer, default=1920)
    height: Mapped[int] = mapped_column(Integer, default=1080)
    orientation: Mapped[str] = mapped_column(String(16), default="landscape")
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    site: Mapped[Site] = relationship(back_populates="screens")
    device: Mapped[Device | None] = relationship(back_populates="screen")


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"
    __table_args__ = (Index("ix_enroll_tokens_expires", "expires_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (Index("ix_media_org_status", "org_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    original_filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[MediaKind] = mapped_column(_enum(MediaKind))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str] = mapped_column(Text)
    status: Mapped[MediaStatus] = mapped_column(_enum(MediaStatus), default=MediaStatus.UPLOADED)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    playlists: Mapped[list[PlaylistItem]] = relationship(back_populates="media")


class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_playlists_org_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    items: Mapped[list[PlaylistItem]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistItem.position"
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_items_position"),
        Index("ix_items_media", "media_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    playlist: Mapped[Playlist] = relationship(back_populates="items")
    media: Mapped[Media] = relationship(back_populates="playlists")


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_schedules_window"),
        Index("ix_schedules_site_active", "site_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(160))
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    site: Mapped[Site] = relationship(back_populates="schedules")
    playlist: Mapped[Playlist] = relationship()


class Manifest(Base):
    __tablename__ = "manifests"
    __table_args__ = (UniqueConstraint("device_id", "version", name="uq_manifests_device_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    screen_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_created", "org_id", "created_at"),
        Index("ix_events_device_created", "device_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(32))
    site_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    type: Mapped[str] = mapped_column(String(64))
    level: Mapped[EventLevel] = mapped_column(_enum(EventLevel), default=EventLevel.INFO)
    message: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (Index("ix_commands_device_status", "device_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    type: Mapped[CommandType] = mapped_column(_enum(CommandType))
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CommandStatus] = mapped_column(
        _enum(CommandStatus), default=CommandStatus.PENDING
    )
    issued_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaProcessingJob(Base):
    __tablename__ = "media_processing_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    media_id: Mapped[str] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"))
    task_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )