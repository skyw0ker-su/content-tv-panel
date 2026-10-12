"""Agent entry point. Keeps the TV in step with the server and keeps playing from the local copy when the server is down."""

import json
import logging
import signal
import threading
from datetime import datetime
from pathlib import Path

import httpx
import vlc

from .api import ServerApi
from .cache import IntegrityError, sync_media
from .config import AgentConfig, load_config
from .playback import PlaybackThread
from .schedule import active_playlist

log = logging.getLogger("signage_agent")

AGENT_VERSION = "0.1.0"
MANIFEST_FILE = "manifest.json"


class Agent:
    def __init__(self, config: AgentConfig, api: ServerApi, vlc_instance: vlc.Instance, now=datetime.now) -> None:
        self._config = config
        self._api = api
        self._vlc = vlc_instance
        self._now = now
        self._manifest = _load_manifest(config.state_dir)
        self._etag = self._manifest["etag"] if self._manifest else None
        self._cache_used = 0
        self._playback: PlaybackThread | None = None
        self._playing: tuple[int, int] | None = None  # (playlist id, playlist version)

    def tick(self) -> None:
        self._refresh_manifest()
        self._apply_schedule()
        reply = self._heartbeat()
        if reply.get("preview_requested"):
            self._send_preview()

    def shutdown(self) -> None:
        self._stop_playback()

    def _refresh_manifest(self) -> None:
        try:
            fresh = self._api.get_manifest(self._etag)
        except httpx.HTTPError as exc:
            log.warning("server unreachable, playing from the last manifest: %s", exc)
            return
        if fresh is None:
            return
        try:
            self._cache_used = sync_media(fresh, self._config.cache_dir, self._api)
        except (httpx.HTTPError, IntegrityError, OSError) as exc:
            log.error("media sync failed, keeping the previous manifest: %s", exc)
            return
        self._manifest = fresh
        self._etag = fresh["etag"]
        _save_manifest(self._config.state_dir, fresh)
        log.info("manifest updated: %d playlists", len(fresh["playlists"]))

    def _apply_schedule(self) -> None:
        plan = active_playlist(self._manifest, self._now()) if self._manifest else None
        key = (plan["id"], plan["version"]) if plan else None
        still_running = self._playback is not None and self._playback.is_alive()
        if key == self._playing and (key is None or still_running):
            return
        self._stop_playback()
        self._playing = key
        if plan is None:
            log.info("no playlist scheduled, screen is idle")
            return
        self._playback = PlaybackThread(plan["items"], self._config.cache_dir, self._vlc)
        self._playback.start()
        log.info("playing playlist %s (version %s)", plan["id"], plan["version"])

    def _stop_playback(self) -> None:
        if self._playback is not None:
            self._playback.stop()
            self._playback.join(timeout=5)
        self._playback = None

    def _heartbeat(self) -> dict:
        alive = self._playback is not None and self._playback.is_alive()
        payload = {
            "current_media_sha256": self._playback.current_sha256 if alive else None,
            "playlist_version": self._playing[1] if self._playing else None,
            "cache_used_bytes": self._cache_used,
            "agent_version": AGENT_VERSION,
        }
        try:
            return self._api.heartbeat(payload)
        except httpx.HTTPError as exc:
            log.warning("heartbeat failed: %s", exc)
            return {}

    def _send_preview(self) -> None:
        if self._playback is None or not self._playback.is_alive():
            return
        path = self._config.state_dir / "preview.jpg"
        if not self._playback.snapshot(path):
            return
        try:
            self._api.upload_preview(path.read_bytes())
        except httpx.HTTPError as exc:
            log.warning("preview upload failed: %s", exc)


def _load_manifest(state_dir: Path) -> dict | None:
    path = state_dir / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        log.warning("saved manifest is unreadable, starting without one")
        return None


def _save_manifest(state_dir: Path, manifest: dict) -> None:
    tmp = state_dir / f"{MANIFEST_FILE}.part"
    tmp.write_text(json.dumps(manifest), encoding="utf-8")
    tmp.replace(state_dir / MANIFEST_FILE)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    config.state_dir.mkdir(parents=True, exist_ok=True)

    instance = vlc.Instance("--no-video-title-show", "--quiet", "--snapshot-format=jpg")
    agent = Agent(config, ServerApi(config.server_url, config.device_token), instance)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    log.info("agent %s started", AGENT_VERSION)
    while not stop.is_set():
        try:
            agent.tick()
        except Exception:
            log.exception("tick failed, will retry")
        stop.wait(config.poll_interval)
    agent.shutdown()


if __name__ == "__main__":
    main()
