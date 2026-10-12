from datetime import datetime

from signage_agent.schedule import active_playlist, window_applies

MON, TUE, SUN = 0, 1, 6


def schedule(**overrides) -> dict:
    base = {
        "id": 1,
        "playlist_id": 10,
        "days": [MON, TUE, 2, 3, 4],
        "start_time": "08:00",
        "end_time": "12:00",
        "priority": 0,
        "valid_from": None,
        "valid_to": None,
    }
    return {**base, **overrides}


def at(day: str, hm: str) -> datetime:
    # 2026-10-12 is a Monday
    return datetime.fromisoformat(f"{day}T{hm}:00")


def test_daytime_window_inside_and_outside():
    s = schedule()
    assert window_applies(s, at("2026-10-12", "09:00"))
    assert not window_applies(s, at("2026-10-12", "12:00"))  # end is exclusive
    assert not window_applies(s, at("2026-10-12", "07:59"))


def test_weekday_filter():
    s = schedule(days=[MON])
    assert window_applies(s, at("2026-10-12", "09:00"))  # Monday
    assert not window_applies(s, at("2026-10-13", "09:00"))  # Tuesday


def test_overnight_window_covers_early_morning_of_next_day():
    s = schedule(days=[MON], start_time="22:00", end_time="06:00")
    assert window_applies(s, at("2026-10-12", "23:30"))  # started Monday
    assert window_applies(s, at("2026-10-13", "01:00"))  # still Monday's window
    assert not window_applies(s, at("2026-10-13", "07:00"))
    assert not window_applies(s, at("2026-10-11", "01:00"))  # started Sunday, Sunday not in days


def test_validity_dates_use_window_start_date():
    s = schedule(days=[MON], start_time="22:00", end_time="06:00", valid_to="2026-10-12")
    assert window_applies(s, at("2026-10-13", "01:00"))  # started on the 12th, still valid
    assert not window_applies(s, at("2026-10-19", "01:00"))


def test_highest_priority_then_newest_wins():
    manifest = {
        "schedules": [
            schedule(id=1, playlist_id=10, priority=0),
            schedule(id=2, playlist_id=20, priority=5),
            schedule(id=3, playlist_id=30, priority=5),
        ],
        "playlists": [
            {"id": 10, "version": 1, "items": []},
            {"id": 20, "version": 1, "items": []},
            {"id": 30, "version": 1, "items": []},
        ],
    }
    chosen = active_playlist(manifest, at("2026-10-12", "09:00"))
    assert chosen["id"] == 30


def test_no_active_window_returns_none():
    manifest = {"schedules": [schedule()], "playlists": [{"id": 10, "version": 1, "items": []}]}
    assert active_playlist(manifest, at("2026-10-12", "20:00")) is None
