"""Plays one playlist full screen through VLC, looping until stopped."""

import threading
import time
from pathlib import Path

import vlc


class PlaybackThread(threading.Thread):
    def __init__(self, items: list[dict], cache_dir: Path, vlc_instance: vlc.Instance) -> None:
        super().__init__(name="playback", daemon=True)
        self._items = items
        self._cache_dir = cache_dir
        self._vlc = vlc_instance
        self._player = vlc_instance.media_player_new()
        self._stop_event = threading.Event()
        self.current_sha256: str | None = None

    def run(self) -> None:
        self._player.set_fullscreen(True)
        try:
            while not self._stop_event.is_set():
                for item in self._items:
                    if self._stop_event.is_set():
                        break
                    self._play_item(item)
        finally:
            self._player.stop()
            self._player.release()
            self.current_sha256 = None

    def stop(self) -> None:
        self._stop_event.set()

    def snapshot(self, dest: Path) -> bool:
        """Save the current frame as JPEG. Returns False when nothing is on screen (for example, audio)."""
        return self._player.video_take_snapshot(0, str(dest), 0, 0) == 0

    def _play_item(self, item: dict) -> None:
        media = self._vlc.media_new_path(str(self._cache_dir / item["sha256"]))
        limit = item.get("duration_sec")
        if item["kind"] == "image" and limit:
            media.add_option(f":image-duration={limit}")
        self._player.set_media(media)
        self.current_sha256 = item["sha256"]
        self._player.play()

        started = time.monotonic()
        while not self._stop_event.is_set():
            state = self._player.get_state()
            if state in (vlc.State.Ended, vlc.State.Error):
                break
            if limit and time.monotonic() - started >= limit:
                break
            time.sleep(0.25)
        self._player.stop()
