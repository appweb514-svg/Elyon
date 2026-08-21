from __future__ import annotations

import datetime as dt

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
    site_id: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=120)
    role: Role = Role.VIEWER
    org_id: str | None = None
    site_id: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    site_id: str | None = None


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


class ScreenPatch(BaseModel):
    name: str | None = None
    width: int | None = None
    height: int | None = None
    orientation: str | None = None
    device_id: str | None = None
    layout: ScreenLayout | None = None


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
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class DevicePatch(BaseModel):
    name: str | None = None
    site_id: str | None = None


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
    created_at: dt.datetime

    model_config = {"from_attributes": True}


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
    name: str
    description: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class PlaylistDetailOut(PlaylistOut):
    items: list[PlaylistItemOut] = []


class ScheduleCreate(BaseModel):
    site_id: str
    playlist_id: str
    name: str = Field(min_length=1, max_length=160)
    start_at: dt.datetime
    end_at: dt.datetime
    priority: int = 0
    is_active: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    playlist_id: str | None = None
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None
    priority: int | None = None
    is_active: bool | None = None


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
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class HeartbeatIn(BaseModel):
    state: str = "idle"
    current_media_id: str | None = None
    storage_free_bytes: int | None = None
    agent_version: str | None = None


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