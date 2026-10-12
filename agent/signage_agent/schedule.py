"""Decides which playlist should be on screen right now. Pure functions, no I/O, so it works offline."""

from datetime import date, datetime, time, timedelta


def _window_start_day(schedule: dict, now: datetime) -> date | None:
    """Return the date on which the window active at `now` started, or None if no window is active.

    Uses the device's local time. An overnight window (end earlier than start) that began yesterday
    is still active in the early morning.
    """
    start = time.fromisoformat(schedule["start_time"])
    end = time.fromisoformat(schedule["end_time"])
    current = now.time()
    today = now.date()
    if start < end:
        return today if start <= current < end else None
    if current >= start:
        return today
    if current < end:
        return today - timedelta(days=1)
    return None


def window_applies(schedule: dict, now: datetime) -> bool:
    started = _window_start_day(schedule, now)
    if started is None or started.weekday() not in schedule["days"]:
        return False
    if schedule["valid_from"] and started < date.fromisoformat(schedule["valid_from"]):
        return False
    if schedule["valid_to"] and started > date.fromisoformat(schedule["valid_to"]):
        return False
    return True


def active_playlist(manifest: dict, now: datetime) -> dict | None:
    """Return the playlist (with items) that should play now, or None.

    When several windows overlap, the highest priority wins; among equal priorities the newer schedule wins.
    """
    candidates = [s for s in manifest.get("schedules", []) if window_applies(s, now)]
    if not candidates:
        return None
    best = max(candidates, key=lambda s: (s["priority"], s["id"]))
    return next((p for p in manifest["playlists"] if p["id"] == best["playlist_id"]), None)
