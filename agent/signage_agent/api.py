"""HTTP client for the server. All calls carry the device token."""

import hashlib
from pathlib import Path

import httpx


class ServerApi:
    def __init__(self, base_url: str, device_token: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {device_token}"},
            timeout=timeout,
        )

    def get_manifest(self, etag: str | None) -> dict | None:
        """Return the new manifest, or None if it has not changed since `etag`."""
        headers = {"If-None-Match": f'"{etag}"'} if etag else {}
        response = self._client.get("/api/agent/manifest", headers=headers)
        if response.status_code == 304:
            return None
        response.raise_for_status()
        return response.json()

    def download_media(self, sha256: str, dest: Path) -> str:
        digest = hashlib.sha256()
        with self._client.stream("GET", f"/api/agent/media/{sha256}") as response:
            response.raise_for_status()
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    digest.update(chunk)
                    out.write(chunk)
        return digest.hexdigest()

    def heartbeat(self, payload: dict) -> dict:
        response = self._client.post("/api/agent/heartbeat", json=payload)
        response.raise_for_status()
        return response.json()

    def upload_preview(self, jpeg: bytes) -> None:
        response = self._client.post(
            "/api/agent/preview",
            content=jpeg,
            headers={"Content-Type": "image/jpeg"},
        )
        response.raise_for_status()
