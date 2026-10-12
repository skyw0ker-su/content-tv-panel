import hashlib
from pathlib import Path

import pytest

from signage_agent.cache import IntegrityError, referenced_media, sync_media


class FakeSource:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.downloads: list[str] = []

    def download_media(self, sha256: str, dest: Path) -> str:
        self.downloads.append(sha256)
        data = self.blobs[sha256]
        dest.write_bytes(data)
        return hashlib.sha256(data).hexdigest()


def manifest_for(blobs: dict[str, bytes], used: list[str]) -> dict:
    return {
        "playlists": [{"id": 1, "version": 1, "items": [{"sha256": sha, "kind": "video", "duration_sec": None} for sha in used]}],
        "media": {sha: {"kind": "video", "mime": "video/mp4", "size": len(blobs[sha])} for sha in used},
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_downloads_missing_files_and_reports_size(tmp_path):
    a, b = b"alpha clip", b"beta clip!"
    blobs = {sha(a): a, sha(b): b}
    source = FakeSource(blobs)

    total = sync_media(manifest_for(blobs, [sha(a), sha(b)]), tmp_path, source)

    assert total == len(a) + len(b)
    assert (tmp_path / sha(a)).read_bytes() == a
    assert sorted(source.downloads) == sorted([sha(a), sha(b)])


def test_skips_files_already_cached(tmp_path):
    a = b"cached clip"
    blobs = {sha(a): a}
    (tmp_path / sha(a)).write_bytes(a)
    source = FakeSource(blobs)

    sync_media(manifest_for(blobs, [sha(a)]), tmp_path, source)

    assert source.downloads == []


def test_removes_files_nothing_references(tmp_path):
    keep, stale = b"keep me", b"old playlist"
    blobs = {sha(keep): keep}
    (tmp_path / sha(stale)).write_bytes(stale)
    (tmp_path / "leftover.part").write_bytes(b"partial")

    sync_media(manifest_for(blobs, [sha(keep)]), tmp_path, FakeSource(blobs))

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([sha(keep)])


def test_hash_mismatch_is_rejected_and_not_cached(tmp_path):
    promised = sha(b"what the manifest promised")
    blobs = {promised: b"something else entirely"}
    manifest = {
        "playlists": [{"id": 1, "version": 1, "items": [{"sha256": promised, "kind": "video", "duration_sec": None}]}],
        "media": {promised: {"kind": "video", "mime": "video/mp4", "size": len(blobs[promised])}},
    }

    with pytest.raises(IntegrityError):
        sync_media(manifest, tmp_path, FakeSource(blobs))
    assert not (tmp_path / promised).exists()
    assert not (tmp_path / f"{promised}.part").exists()


def test_referenced_media_maps_hash_to_size():
    a = b"x" * 10
    blobs = {sha(a): a}
    assert referenced_media(manifest_for(blobs, [sha(a)])) == {sha(a): 10}
