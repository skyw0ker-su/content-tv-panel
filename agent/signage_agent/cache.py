"""Keeps the local media cache in line with the manifest. Files are named by their SHA-256."""

import hashlib
from pathlib import Path
from typing import Protocol


class IntegrityError(Exception):
    """A downloaded file does not match the hash or size promised by the manifest."""


class MediaSource(Protocol):
    def download_media(self, sha256: str, dest: Path) -> str:
        """Write the media to `dest` and return the SHA-256 of what was actually received."""


def referenced_media(manifest: dict) -> dict[str, int]:
    """Map sha256 -> size for every file the manifest's playlists use."""
    sizes: dict[str, int] = {}
    for playlist in manifest["playlists"]:
        for item in playlist["items"]:
            sha256 = item["sha256"]
            sizes[sha256] = manifest["media"][sha256]["size"]
    return sizes


def sync_media(manifest: dict, cache_dir: Path, source: MediaSource) -> int:
    """Download missing files, verify them, then delete files nothing references. Returns cache size in bytes."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    wanted = referenced_media(manifest)

    for sha256, size in wanted.items():
        target = cache_dir / sha256
        if target.is_file() and target.stat().st_size == size:
            continue
        partial = cache_dir / f"{sha256}.part"
        received = source.download_media(sha256, partial)
        if received != sha256 or partial.stat().st_size != size:
            partial.unlink(missing_ok=True)
            raise IntegrityError(f"media {sha256} failed verification")
        partial.replace(target)

    for path in cache_dir.iterdir():
        if path.is_file() and (path.name.endswith(".part") or path.name not in wanted):
            path.unlink()

    return sum(wanted.values())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
