"""A video id read passively off the screen.

When the device finds an id already rendered in the interface, nothing
needs to be shared, pressed, or paired: the URL is known at ingest. This
is the cheapest path to a citable link and the only one that sends no
signal back to the platform.
"""

from app.db import SessionLocal
from app.models import TikTokPost

_BASE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "tiktok::someuser::hello",
    "captured_at": "2026-09-14T12:00:00Z",
}


def _ingest(client, api_key, payload):
    return client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [{**_BASE, "payload": payload}]},
        headers={"X-API-Key": api_key},
    )


def test_an_id_on_screen_becomes_the_video_url_at_ingest(client, api_key):
    _ingest(
        client,
        api_key,
        {
            "author_handle": "someuser",
            "caption": "hello world",
            "video_id_hint": "7301234567890123456",
        },
    )

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id == "7301234567890123456"
        assert post.video_url == (
            "https://www.tiktok.com/@someuser/video/7301234567890123456"
        )


def test_no_hint_leaves_the_link_empty(client, api_key):
    _ingest(client, api_key, {"author_handle": "someuser", "caption": "hello world"})

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id is None
        assert post.video_url is None


def test_a_hint_that_is_not_id_shaped_is_refused(client, api_key):
    # Counts, timestamps and follower numbers also appear on screen; only
    # an 18-19 digit token is plausibly a video id.
    for junk in ("123", "74.9K", "not-an-id", "2026-09-14", "7301234567890123456789"):
        _ingest(
            client,
            api_key,
            {
                "author_handle": "someuser",
                "caption": f"caption {junk}",
                "video_id_hint": junk,
            },
        )

    with SessionLocal() as session:
        assert session.query(TikTokPost).filter(TikTokPost.video_id.isnot(None)).count() == 0


def test_an_eighteen_digit_id_is_accepted(client, api_key):
    # The 19-digit era began in 2020; older ids are shorter and a study
    # may well capture a resurfaced older video.
    _ingest(
        client,
        api_key,
        {
            "author_handle": "someuser",
            "caption": "an older video",
            "video_id_hint": "685123456789012345",
        },
    )

    with SessionLocal() as session:
        assert session.query(TikTokPost).one().video_id == "685123456789012345"


def test_the_dashboard_links_a_passively_found_id(client, api_key):
    _ingest(
        client,
        api_key,
        {
            "author_handle": "someuser",
            "caption": "hello world",
            "video_id_hint": "7301234567890123456",
        },
    )
    body = client.get("/dashboard?key=test-admin-key&platform=tiktok").text
    assert 'href="https://www.tiktok.com/@someuser/video/7301234567890123456"' in body
    assert "not shared" not in body
