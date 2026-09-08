from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from elyon_api.models import (
    CommandType,
    DeviceStatus,
    EventLevel,
    MediaKind,
    MediaStatus,
    Role,
)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool
    org_id: str | None = None
    team_id: str | None = None
    quota_bytes: int = 0
    site_id: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=120)
    role: Role = Role.VIEWER
    org_id: str | None = None
    team_id: str | None = None
    quota_bytes: int = Field(default=0, ge=0)
    site_id: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    site_id: str | None = None
    team_id: str | None = None
    quota_bytes: int | None = Field(default=None, ge=0)


class ProfilePatch(BaseModel):
    """Modification de son propre profil (utilisateur connecté)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = None
    password: str | None = Field(default=None, min_length=12)
    current_password: str | None = None


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # 0 = illimité ; défaut 15 Go par équipe.
    quota_bytes: int = Field(default=15 * 1024**3, ge=0)
    # Org cible : requis pour un superadmin sans organisation.
    org_id: str | None = None


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    quota_bytes: int | None = Field(default=None, ge=0)


class TeamOut(BaseModel):
    id: str
    org_id: str
    name: str
    quota_bytes: int
    used_bytes: int = 0
    members: int = 0
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: str
    quota_bytes: int

    model_config = {"from_attributes": True}


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Europe/Paris"
    address: str | None = None


class SiteOut(BaseModel):
    id: str
    org_id: str
    name: str
    timezone: str
    address: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ScreenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    width: int = 1920
    height: int = 1080
    orientation: str = "landscape"
    device_id: str | None = None
    layout: ScreenLayout | None = None


class ScreenLayoutZone(BaseModel):
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    w: float = Field(ge=0, le=100)
    h: float = Field(ge=0, le=100)
    media_id: str | None = None
    playlist_id: str | None = None


class ScreenLayout(BaseModel):
    mode: str = Field(description="fullscreen|grid_2x2|split_h|split_v|custom")
    zones: list[ScreenLayoutZone] = Field(default_factory=list)


class WidgetIn(BaseModel):
    """Widget d'information affiché sur l'écran (météo, RSS, texte)."""

    type: str = Field(description="weather|rss|text|clock|html")
    position: str = Field(
        default="bottom-left",
        description=(
            "top-left|top-right|bottom-left|bottom-center|bottom-right|bottom-ticker "
            "(barre du haut : météo à gauche / horloge à droite ; "
            "bottom-ticker : flux RSS défilant en barre pleine largeur)"
        ),
    )
    visible: bool = True
    params: dict[str, str | int | float | None] = Field(default_factory=dict)


class WidgetOut(WidgetIn):
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])


class ScreenPatch(BaseModel):
    name: str | None = None
    width: int | None = None
    height: int | None = None
    orientation: str | None = None
    device_id: str | None = None
    layout: ScreenLayout | None = None
    widgets: list[WidgetIn] | None = None


class ScreenOut(BaseModel):
    id: str
    org_id: str
    site_id: str
    name: str
    width: int
    height: int
    orientation: str
    device_id: str | None = None
    layout: ScreenLayout | None = None
    widgets: list[WidgetOut] | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class DeviceStatusDetail(BaseModel):
    raw: DeviceStatus
    computed: str
    last_seen_at: dt.datetime | None = None
    screen_id: str | None = None
    manifest_version: int | None = None


class DeviceOut(BaseModel):
    id: str
    org_id: str
    site_id: str | None = None
    screen_id: str | None = None
    name: str
    serial: str
    status: DeviceStatus
    computed_status: str | None = None
    last_seen_at: dt.datetime | None = None
    player_state: str | None = None
    current_media_id: str | None = None
    is_preview: bool = False
    uptime_seconds: int | None = None
    load_avg: float | None = None
    memory_percent: float | None = None
    cpu_percent: float | None = None
    storage_free_bytes: int | None = None
    lan_ip: str | None = None
    wifi_ssid: str | None = None
    network: dict[str, Any] | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class DevicePatch(BaseModel):
    name: str | None = None
    site_id: str | None = None
    is_preview: bool | None = None
    screen_id: str | None = None


class MediaRename(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class MediaShowRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=32)
    duration_seconds: int | None = Field(default=None, ge=1)


class EnrollTokenOut(BaseModel):
    id: str
    site_id: str
    code: str
    expires_at: dt.datetime


class EnrollRequest(BaseModel):
    serial: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    site_code: str = Field(min_length=6, max_length=8)
    public_key: str | None = None


class EnrollResponse(BaseModel):
    device_id: str
    token: str


class MediaOut(BaseModel):
    id: str
    org_id: str
    name: str
    original_filename: str
    kind: MediaKind
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    status: MediaStatus
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    team_name: str | None = None
    pages_count: int | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class TeamShareIn(BaseModel):
    team_id: str = Field(min_length=1, max_length=32)


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class PlaylistItemIn(BaseModel):
    media_id: str
    duration_seconds: int | None = Field(default=None, ge=1)


class PlaylistItemOut(BaseModel):
    id: str
    media_id: str
    position: int
    duration_seconds: int | None = None

    model_config = {"from_attributes": True}


class PlaylistOut(BaseModel):
    id: str
    org_id: str
    team_id: str | None = None
    team_name: str | None = None
    name: str
    description: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class PlaylistDetailOut(PlaylistOut):
    items: list[PlaylistItemOut] = []
    published_version: int | None = None
    draft_changed: bool = False


class PlaylistValidationOut(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    item_count: int
    total_duration_seconds: int


class PlaylistRevisionOut(BaseModel):
    id: str
    playlist_id: str
    version: int
    status: str
    items: list[PlaylistItemOut]
    created_by: str | None = None
    created_at: dt.datetime


class PlaylistDiffOut(BaseModel):
    published_version: int | None = None
    draft: list[PlaylistItemOut]
    published: list[PlaylistItemOut]
    added: list[str]
    removed: list[str]
    reordered: bool
    changed: bool


class PlaylistDuplicateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class ScheduleCreate(BaseModel):
    site_id: str
    playlist_id: str
    name: str = Field(min_length=1, max_length=160)
    start_at: dt.datetime
    end_at: dt.datetime
    priority: int = 0
    is_active: bool = True
    # Optionnel : cible un seul écran (device). Absent = tous les écrans du site.
    device_id: str | None = None


class SchedulePatch(BaseModel):
    name: str | None = None
    playlist_id: str | None = None
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None
    priority: int | None = None
    is_active: bool | None = None
    device_id: str | None = None


class ScheduleOut(BaseModel):
    id: str
    org_id: str
    site_id: str
    playlist_id: str
    name: str
    start_at: dt.datetime
    end_at: dt.datetime
    priority: int
    is_active: bool
    device_id: str | None = None
    # Renseigné uniquement quand la liste est demandée pour un device précis :
    # True = ce planning est masqué sur CET écran (exclusion locale).
    excluded_for_this_device: bool = False
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ScheduleExclusionIn(BaseModel):
    device_id: str


class HeartbeatIn(BaseModel):
    state: str = "idle"
    current_media_id: str | None = None
    storage_free_bytes: int | None = None
    agent_version: str | None = None
    uptime_seconds: int | None = None
    load_avg: float | None = None
    memory_percent: float | None = None
    cpu_percent: float | None = None
    lan_ip: str | None = None
    wifi_ssid: str | None = None


class CommandIn(BaseModel):
    type: CommandType
    payload: str | None = None


class CommandOut(BaseModel):
    id: str
    device_id: str
    type: CommandType
    payload: str | None = None
    status: str
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class CommandAck(BaseModel):
    error: str | None = None


class EventOut(BaseModel):
    id: str
    org_id: str
    site_id: str | None = None
    device_id: str | None = None
    type: str
    level: EventLevel
    message: str
    detail: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ManifestOut(BaseModel):
    version: int
    payload: str
    signature: str
    published_at: dt.datetime

    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: str
    org_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None
    detail: str | None = None
    ip: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}