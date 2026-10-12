import hashlib

from conftest import ADMIN


def upload(client, data: bytes, mime: str = "video/mp4", name: str = "clip.mp4"):
    return client.post("/api/media", files={"file": (name, data, mime)}, headers=ADMIN)


def create_device(client, name: str = "tv-1") -> tuple[int, str]:
    body = client.post("/api/devices", json={"name": name}, headers=ADMIN).json()
    return body["id"], body["token"]


def agent(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_admin_endpoints_need_admin_token(client):
    assert client.post("/api/devices", json={"name": "x"}).status_code == 401
    assert client.post("/api/devices", json={"name": "x"}, headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_upload_and_download_media(client):
    data = b"fake video bytes"
    response = upload(client, data)
    assert response.status_code == 201
    media = response.json()
    assert media["kind"] == "video"
    assert media["sha256"] == hashlib.sha256(data).hexdigest()

    _, token = create_device(client)
    downloaded = client.get(f"/api/agent/media/{media['sha256']}", headers=agent(token))
    assert downloaded.status_code == 200
    assert downloaded.content == data


def test_unsupported_media_type_is_rejected(client):
    response = upload(client, b"%PDF", mime="application/pdf", name="doc.pdf")
    assert response.status_code == 415


def test_media_download_needs_device_token(client):
    sha = upload(client, b"another clip").json()["sha256"]
    assert client.get(f"/api/agent/media/{sha}").status_code == 401


def test_manifest_contains_device_schedule_and_supports_etag(client):
    image = upload(client, b"\x89PNG-test", mime="image/png", name="ad.png").json()
    playlist = client.post(
        "/api/playlists",
        json={"name": "morning", "items": [{"media_id": image["id"]}]},
        headers=ADMIN,
    ).json()
    assert playlist["items"][0]["duration_sec"] == 10  # images get a default display time

    device_id, token = create_device(client, "lobby-tv")
    client.post(
        "/api/schedules",
        json={
            "playlist_id": playlist["id"],
            "device_id": device_id,
            "days": [0, 1, 2, 3, 4],
            "start_time": "08:00",
            "end_time": "12:00",
        },
        headers=ADMIN,
    )

    manifest = client.get("/api/agent/manifest", headers=agent(token))
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["device"]["id"] == device_id
    assert any(p["id"] == playlist["id"] for p in body["playlists"])
    assert image["sha256"] in body["media"]
    assert any(s["playlist_id"] == playlist["id"] for s in body["schedules"])

    again = client.get("/api/agent/manifest", headers={**agent(token), "If-None-Match": manifest.headers["ETag"]})
    assert again.status_code == 304


def test_playlist_update_bumps_version(client):
    clip = upload(client, b"versioned clip").json()
    playlist = client.post(
        "/api/playlists", json={"name": "v", "items": [{"media_id": clip["id"]}]}, headers=ADMIN
    ).json()
    updated = client.put(
        f"/api/playlists/{playlist['id']}",
        json={"name": "v", "items": [{"media_id": clip["id"], "duration_sec": 30}]},
        headers=ADMIN,
    ).json()
    assert updated["version"] == playlist["version"] + 1
    assert updated["items"][0]["duration_sec"] == 30


def test_heartbeat_and_on_demand_preview(client):
    device_id, token = create_device(client, "kiosk")

    beat = client.post(
        "/api/agent/heartbeat",
        json={"agent_version": "0.1.0", "cache_used_bytes": 1024},
        headers=agent(token),
    )
    assert beat.json() == {"preview_requested": False}

    assert client.post(f"/api/devices/{device_id}/preview-request", headers=ADMIN).status_code == 202
    beat = client.post("/api/agent/heartbeat", json={"agent_version": "0.1.0"}, headers=agent(token))
    assert beat.json() == {"preview_requested": True}

    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    sent = client.post(
        "/api/agent/preview",
        content=jpeg,
        headers={**agent(token), "Content-Type": "image/jpeg"},
    )
    assert sent.status_code == 204

    shown = client.get(f"/api/devices/{device_id}/preview", headers=ADMIN)
    assert shown.status_code == 200
    assert shown.content == jpeg

    beat = client.post("/api/agent/heartbeat", json={"agent_version": "0.1.0"}, headers=agent(token))
    assert beat.json() == {"preview_requested": False}


def test_schedule_rejects_empty_window(client):
    clip = upload(client, b"window clip").json()
    playlist = client.post(
        "/api/playlists", json={"name": "w", "items": [{"media_id": clip["id"]}]}, headers=ADMIN
    ).json()
    response = client.post(
        "/api/schedules",
        json={"playlist_id": playlist["id"], "days": [0], "start_time": "09:00", "end_time": "09:00"},
        headers=ADMIN,
    )
    assert response.status_code == 422
