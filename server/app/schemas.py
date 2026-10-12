from datetime import date, datetime, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Weekday = Annotated[int, Field(ge=0, le=6)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    mime: str
    sha256: str
    size: int
    created_at: datetime


class PlaylistItemIn(BaseModel):
    media_id: int
    duration_sec: int | None = Field(default=None, ge=1, le=86400)


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    items: list[PlaylistItemIn] = Field(min_length=1)


class PlaylistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    media_id: int
    duration_sec: int | None


class PlaylistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: int
    items: list[PlaylistItemOut]


class ScheduleIn(BaseModel):
    playlist_id: int
    device_id: int | None = None
    days: list[Weekday] = Field(min_length=1, max_length=7)
    start_time: time
    end_time: time
    priority: int = 0
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def check_window(self) -> "ScheduleIn":
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from is after valid_to")
        return self


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    playlist_id: int
    device_id: int | None
    days: list[int]
    start_time: str
    end_time: str
    priority: int
    valid_from: date | None
    valid_to: date | None


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DeviceCreated(BaseModel):
    id: int
    name: str
    token: str  # shown once; the server keeps only its hash


class DeviceOut(BaseModel):
    id: int
    name: str
    online: bool
    last_seen_at: datetime | None
    current_media_sha256: str | None
    playlist_version: int | None
    cache_used_bytes: int | None
    agent_version: str | None
    preview_requested: bool
    has_preview: bool


class Heartbeat(BaseModel):
    current_media_sha256: Sha256 | None = None
    playlist_version: int | None = None
    cache_used_bytes: int | None = Field(default=None, ge=0)
    agent_version: str = Field(min_length=1, max_length=32)
