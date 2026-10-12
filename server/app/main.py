"""HTTP API: admin endpoints for content, playlists, schedules and devices, plus the endpoints the agents on the mini PCs use."""

import hashlib
import json
import os
import secrets
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas
from .config import settings
from .db import Base, engine, get_db
from .models import utcnow

ONLINE_WINDOW = timedelta(seconds=90)
DEFAULT_IMAGE_SECONDS = 10
MAX_PREVIEW_BYTES = 5 * 1024 * 1024
KIND_BY_MIME_PREFIX = {"video/": "video", "audio/": "audio", "image/": "image"}

DbSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    (settings.storage_dir / "previews").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Content TV Panel", version="0.1.0", lifespan=lifespan)


# --- auth -------------------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if not settings.admin_token:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "invalid admin token")


def current_device(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> models.Device:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    device = db.scalar(select(models.Device).where(models.Device.token_hash == hash_token(token)))
    if device is None:
        raise HTTPException(401, "unknown device token")
    return device


CurrentDevice = Annotated[models.Device, Depends(current_device)]
AdminOnly = [Depends(require_admin)]


# --- media ------------------------------------------------------------------


def media_path(sha256: str) -> Path:
    return settings.storage_dir / sha256


def preview_path(device_id: int) -> Path:
    return settings.storage_dir / "previews" / f"{device_id}.jpg"


async def store_upload(file: UploadFile) -> tuple[str, int]:
    """Stream the upload to a temporary file, then move it to its content-addressed name."""
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=settings.storage_dir, suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
        sha256 = digest.hexdigest()
        if not media_path(sha256).exists():
            tmp.replace(media_path(sha256))
        return sha256, size
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/media", status_code=201, response_model=schemas.MediaOut, dependencies=AdminOnly)
async def upload_media(file: UploadFile, db: DbSession) -> models.Media:
    mime = file.content_type or "application/octet-stream"
    kind = next((k for prefix, k in KIND_BY_MIME_PREFIX.items() if mime.startswith(prefix)), None)
    if kind is None:
        raise HTTPException(415, f"unsupported content type: {mime}")
    sha256, size = await store_upload(file)
    media = models.Media(name=file.filename or sha256[:12], kind=kind, mime=mime, sha256=sha256, size=size)
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


@app.get("/api/media", response_model=list[schemas.MediaOut], dependencies=AdminOnly)
def list_media(db: DbSession) -> list[models.Media]:
    return list(db.scalars(select(models.Media).order_by(models.Media.id)))


@app.get("/api/agent/media/{sha256}")
def download_media(
    sha256: Annotated[str, PathParam(pattern=r"^[0-9a-f]{64}$")],
    _device: CurrentDevice,
    db: DbSession,
) -> FileResponse:
    media = db.scalar(select(models.Media).where(models.Media.sha256 == sha256))
    if media is None or not media_path(sha256).is_file():
        raise HTTPException(404, "media not found")
    return FileResponse(media_path(sha256), media_type=media.mime)


# --- playlists --------------------------------------------------------------


def set_playlist_items(db: Session, playlist: models.Playlist, items: list[schemas.PlaylistItemIn]) -> None:
    new_items = []
    for position, item in enumerate(items):
        media = db.get(models.Media, item.media_id)
        if media is None:
            raise HTTPException(422, f"media {item.media_id} does not exist")
        duration = item.duration_sec
        if duration is None and media.kind == "image":
            duration = DEFAULT_IMAGE_SECONDS
        new_items.append(models.PlaylistItem(position=position, media_id=media.id, duration_sec=duration))
    playlist.items = new_items


@app.post("/api/playlists", status_code=201, response_model=schemas.PlaylistOut, dependencies=AdminOnly)
def create_playlist(body: schemas.PlaylistIn, db: DbSession) -> models.Playlist:
    playlist = models.Playlist(name=body.name, version=1)
    db.add(playlist)
    set_playlist_items(db, playlist, body.items)
    db.commit()
    db.refresh(playlist)
    return playlist


@app.put("/api/playlists/{playlist_id}", response_model=schemas.PlaylistOut, dependencies=AdminOnly)
def update_playlist(playlist_id: int, body: schemas.PlaylistIn, db: DbSession) -> models.Playlist:
    playlist = get_or_404(db, models.Playlist, playlist_id)
    playlist.name = body.name
    set_playlist_items(db, playlist, body.items)
    playlist.version += 1  # devices use the version to notice that the playlist changed
    db.commit()
    db.refresh(playlist)
    return playlist


@app.get("/api/playlists", response_model=list[schemas.PlaylistOut], dependencies=AdminOnly)
def list_playlists(db: DbSession) -> list[models.Playlist]:
    return list(db.scalars(select(models.Playlist).order_by(models.Playlist.id)))


@app.get("/api/playlists/{playlist_id}", response_model=schemas.PlaylistOut, dependencies=AdminOnly)
def get_playlist(playlist_id: int, db: DbSession) -> models.Playlist:
    return get_or_404(db, models.Playlist, playlist_id)


# --- schedules --------------------------------------------------------------


@app.post("/api/schedules", status_code=201, response_model=schemas.ScheduleOut, dependencies=AdminOnly)
def create_schedule(body: schemas.ScheduleIn, db: DbSession) -> models.Schedule:
    get_or_404(db, models.Playlist, body.playlist_id)
    if body.device_id is not None:
        get_or_404(db, models.Device, body.device_id)
    schedule = models.Schedule(
        playlist_id=body.playlist_id,
        device_id=body.device_id,
        days=sorted(set(body.days)),
        start_time=body.start_time.strftime("%H:%M"),
        end_time=body.end_time.strftime("%H:%M"),
        priority=body.priority,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@app.get("/api/schedules", response_model=list[schemas.ScheduleOut], dependencies=AdminOnly)
def list_schedules(db: DbSession) -> list[models.Schedule]:
    return list(db.scalars(select(models.Schedule).order_by(models.Schedule.id)))


@app.delete("/api/schedules/{schedule_id}", status_code=204, dependencies=AdminOnly)
def delete_schedule(schedule_id: int, db: DbSession) -> Response:
    db.delete(get_or_404(db, models.Schedule, schedule_id))
    db.commit()
    return Response(status_code=204)


# --- devices (admin) --------------------------------------------------------


def device_out(device: models.Device) -> schemas.DeviceOut:
    online = device.last_seen_at is not None and utcnow() - device.last_seen_at < ONLINE_WINDOW
    return schemas.DeviceOut(
        id=device.id,
        name=device.name,
        online=online,
        last_seen_at=device.last_seen_at,
        current_media_sha256=device.current_media_sha256,
        playlist_version=device.playlist_version,
        cache_used_bytes=device.cache_used_bytes,
        agent_version=device.agent_version,
        preview_requested=device.preview_requested,
        has_preview=preview_path(device.id).is_file(),
    )


@app.post("/api/devices", status_code=201, response_model=schemas.DeviceCreated, dependencies=AdminOnly)
def create_device(body: schemas.DeviceCreate, db: DbSession) -> schemas.DeviceCreated:
    token = secrets.token_urlsafe(32)
    device = models.Device(name=body.name, token_hash=hash_token(token))
    db.add(device)
    db.commit()
    db.refresh(device)
    return schemas.DeviceCreated(id=device.id, name=device.name, token=token)


@app.get("/api/devices", response_model=list[schemas.DeviceOut], dependencies=AdminOnly)
def list_devices(db: DbSession) -> list[schemas.DeviceOut]:
    return [device_out(d) for d in db.scalars(select(models.Device).order_by(models.Device.id))]


@app.post("/api/devices/{device_id}/preview-request", status_code=202, dependencies=AdminOnly)
def request_preview(device_id: int, db: DbSession) -> dict[str, str]:
    device = get_or_404(db, models.Device, device_id)
    device.preview_requested = True
    db.commit()
    return {"status": "requested"}


@app.get("/api/devices/{device_id}/preview", response_model=None, dependencies=AdminOnly)
def get_preview(device_id: int) -> FileResponse:
    path = preview_path(device_id)
    if not path.is_file():
        raise HTTPException(404, "no preview yet")
    return FileResponse(path, media_type="image/jpeg")


# --- agent endpoints --------------------------------------------------------


def build_manifest(db: Session, device: models.Device) -> dict:
    """Everything a device needs to play offline: its schedules, the playlists they use, and the media files."""
    schedules = list(
        db.scalars(
            select(models.Schedule)
            .where(or_(models.Schedule.device_id == device.id, models.Schedule.device_id.is_(None)))
            .order_by(models.Schedule.id)
        )
    )
    playlist_ids = {s.playlist_id for s in schedules}
    playlists = (
        list(
            db.scalars(
                select(models.Playlist)
                .where(models.Playlist.id.in_(playlist_ids))
                .options(selectinload(models.Playlist.items).selectinload(models.PlaylistItem.media))
                .order_by(models.Playlist.id)
            )
        )
        if playlist_ids
        else []
    )

    media: dict[str, dict] = {}
    playlist_payload = []
    for playlist in playlists:
        items = []
        for item in playlist.items:
            media_row = item.media
            media[media_row.sha256] = {"kind": media_row.kind, "mime": media_row.mime, "size": media_row.size}
            duration = item.duration_sec
            if duration is None and media_row.kind == "image":
                duration = DEFAULT_IMAGE_SECONDS
            items.append({"sha256": media_row.sha256, "kind": media_row.kind, "duration_sec": duration})
        playlist_payload.append({"id": playlist.id, "version": playlist.version, "items": items})

    schedule_payload = [
        {
            "id": s.id,
            "playlist_id": s.playlist_id,
            "days": s.days,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "priority": s.priority,
            "valid_from": s.valid_from.isoformat() if s.valid_from else None,
            "valid_to": s.valid_to.isoformat() if s.valid_to else None,
        }
        for s in schedules
    ]
    body = {
        "device": {"id": device.id, "name": device.name},
        "schedules": schedule_payload,
        "playlists": playlist_payload,
        "media": media,
    }
    etag = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"etag": etag, **body}


@app.get("/api/agent/manifest", response_model=None)
def get_manifest(request: Request, response: Response, device: CurrentDevice, db: DbSession):
    manifest = build_manifest(db, device)
    etag_header = f'"{manifest["etag"]}"'
    if request.headers.get("if-none-match") == etag_header:
        return Response(status_code=304, headers={"ETag": etag_header})
    response.headers["ETag"] = etag_header
    return manifest


@app.post("/api/agent/heartbeat")
def heartbeat(body: schemas.Heartbeat, device: CurrentDevice, db: DbSession) -> dict[str, bool]:
    device.last_seen_at = utcnow()
    device.current_media_sha256 = body.current_media_sha256
    device.playlist_version = body.playlist_version
    device.cache_used_bytes = body.cache_used_bytes
    device.agent_version = body.agent_version
    db.commit()
    return {"preview_requested": device.preview_requested}


@app.post("/api/agent/preview", status_code=204)
async def upload_preview(request: Request, device: CurrentDevice, db: DbSession) -> Response:
    if request.headers.get("content-type", "").split(";")[0].strip() != "image/jpeg":
        raise HTTPException(415, "preview must be image/jpeg")
    data = await request.body()
    if not data or len(data) > MAX_PREVIEW_BYTES:
        raise HTTPException(413, "preview is empty or too large")
    path = preview_path(device.id)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    device.preview_requested = False
    device.preview_updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


# --- helpers ----------------------------------------------------------------


def get_or_404(db: Session, model, row_id: int):
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(404, f"{model.__name__} {row_id} not found")
    return row
