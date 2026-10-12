from datetime import UTC, date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp: SQLite drops tzinfo, so we store UTC without it everywhere."""
    return datetime.now(UTC).replace(tzinfo=None)


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))  # video | audio | image
    mime: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    items: Mapped[list["PlaylistItem"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistItem.position",
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"))
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    playlist: Mapped[Playlist] = relationship(back_populates="items")
    media: Mapped[Media] = relationship()


class Device(Base):
    """One mini PC driving one TV."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_media_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    playlist_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preview_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    preview_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Schedule(Base):
    """Plays a playlist on one device (or on all devices when device_id is NULL).

    days: weekdays 0 (Mon) to 6 (Sun) on which the window starts.
    start_time/end_time: "HH:MM". If end_time is earlier than start_time the window runs overnight.
    """

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    days: Mapped[list[int]] = mapped_column(JSON)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    playlist: Mapped[Playlist] = relationship()
