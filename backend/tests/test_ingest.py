import json

from app.db import SessionLocal
from app.models import CaptureEvent, TikTokPost

_CAPTURE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "tiktok::someuser::hello world",
    "captured_at": "2026-09-14T12:00:00Z",
    "payload": {
        "author_handle": "someuser",
        "caption": "hello world",
        "like_raw": "74.9K",
        "comment_raw": "1,234",
        "share_raw": "88",
        "save_raw": "12.3万",
        "music": "original sound",
        "feed": "For You",
        "is_ad": False,
    },
}


def test_register_rejects_unapproved_email(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "stranger@example.com", "device_id": "d1"},
    )
    assert response.status_code == 403


def test_register_is_idempotent(client):
    first = client.post(
        "/api/auth/register", json={"email": "p1@example.edu", "device_id": "d1"}
    ).json()
    second = client.post(
        "/api/auth/register", json={"email": "p1@example.edu", "device_id": "d1"}
    ).json()
    assert first["api_key"] == second["api_key"]
    assert first["participant_id"] == "P001"


def test_ingest_requires_a_valid_key(client):
    response = client.post(
        "/api/captures/batch",
        json={"device_id": "d1", "captures": [_CAPTURE]},
        headers={"X-API-Key": "nope"},
    )
    assert response.status_code == 401


def test_ingest_structures_counts_and_flags_approximation(client, api_key):
    response = client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [_CAPTURE]},
        headers={"X-API-Key": api_key},
    )
    assert response.json() == {"accepted": 1, "duplicates": 0, "rejected": 0}

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.like_count == 74_900
        assert post.comment_count == 1234
        assert post.save_count == 123_000
        assert post.counts_approximate is True
        assert post.feed == "recommend"
        assert post.video_id is None

        event = session.query(CaptureEvent).one()
        assert json.loads(event.payload)["caption"] == "hello world"


def test_same_post_same_day_is_deduplicated(client, api_key):
    body = {"device_id": "pixel-7a", "captures": [_CAPTURE, _CAPTURE]}
    response = client.post(
        "/api/captures/batch", json=body, headers={"X-API-Key": api_key}
    )
    assert response.json() == {"accepted": 1, "duplicates": 1, "rejected": 0}


def test_unknown_package_is_rejected_not_stored(client, api_key):
    capture = {**_CAPTURE, "platform_package": "com.instagram.android"}
    response = client.post(
        "/api/captures/batch",
        json={"device_id": "d1", "captures": [capture]},
        headers={"X-API-Key": api_key},
    )
    assert response.json() == {"accepted": 0, "duplicates": 0, "rejected": 1}


def test_export_requires_admin_key(client, api_key):
    assert client.get("/api/export/posts.csv?platform=tiktok").status_code == 401
    assert (
        client.get(
            "/api/export/posts.csv?platform=tiktok",
            headers={"X-API-Key": api_key},
        ).status_code
        == 401
    )


def test_export_returns_csv(client, api_key):
    client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [_CAPTURE]},
        headers={"X-API-Key": api_key},
    )
    response = client.get(
        "/api/export/posts.csv?platform=tiktok",
        headers={"X-API-Key": "test-admin-key"},
    )
    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("id,participant_id,captured_at")
    assert "someuser" in lines[1]
