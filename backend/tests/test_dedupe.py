"""A post read before its caption drew is not a second post.

    19:50  '珩舟'  likes=8  caption=None
    19:50  '珩舟'  likes=8  caption='#短发 #lwl'

Identity on the device is author plus the head of the caption, so the
two reads land under two identities and store two rows. The blank one
holds nothing the other does not.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.dedupe import absorb, pairs
from app.parsers import PLATFORM_TABLES

MODEL, _ = PLATFORM_TABLES["douyin"]


def _capture(client, api_key, fingerprint, payload, when="2026-09-19T19:50:00Z"):
    response = client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.ss.android.ugc.aweme",
                    "fingerprint": fingerprint,
                    "captured_at": when,
                    "payload": payload,
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200


def test_the_blank_read_folds_into_the_one_with_the_caption(client, api_key):
    _capture(client, api_key, "douyin::珩舟::", {"author_name": "珩舟", "like_raw": "8"})
    _capture(
        client,
        api_key,
        "douyin::珩舟::#短发 #lwl",
        {"author_name": "珩舟", "like_raw": "8", "caption": "#短发 #lwl"},
    )

    with SessionLocal() as session:
        assert session.query(MODEL).count() == 2
        assert absorb(session, "douyin", apply=True)["blank_rows_folded"] == 1

        kept = session.query(MODEL).one()
        assert kept.caption == "#短发 #lwl"
        assert kept.like_count == 8

    # The observation the device reported is still on file.
    from app.models import CaptureEvent

    with SessionLocal() as session:
        assert session.query(CaptureEvent).count() == 2


def test_a_dry_run_writes_nothing(client, api_key):
    _capture(client, api_key, "douyin::珩舟::", {"author_name": "珩舟", "like_raw": "8"})
    _capture(
        client,
        api_key,
        "douyin::珩舟::#短发",
        {"author_name": "珩舟", "like_raw": "8", "caption": "#短发"},
    )

    with SessionLocal() as session:
        assert absorb(session, "douyin")["blank_rows_folded"] == 1
        assert session.query(MODEL).count() == 2


def test_two_videos_by_one_author_are_left_alone(client, api_key):
    """Ambiguity keeps both rows: a merge in error loses a video."""
    _capture(client, api_key, "douyin::珩舟::", {"author_name": "珩舟"})
    _capture(
        client, api_key, "douyin::珩舟::one", {"author_name": "珩舟", "caption": "one"}
    )
    _capture(
        client, api_key, "douyin::珩舟::two", {"author_name": "珩舟", "caption": "two"}
    )

    with SessionLocal() as session:
        # The blank row carries no counts, and the author has two
        # captioned videos that day, so nothing tells them apart.
        assert pairs(session, "douyin") == []
        assert absorb(session, "douyin", apply=True)["blank_rows_folded"] == 0
        assert session.query(MODEL).count() == 3


def test_counts_pick_the_right_one_of_two(client, api_key):
    _capture(
        client, api_key, "douyin::珩舟::", {"author_name": "珩舟", "like_raw": "8"}
    )
    _capture(
        client,
        api_key,
        "douyin::珩舟::one",
        {"author_name": "珩舟", "like_raw": "8", "caption": "one"},
    )
    _capture(
        client,
        api_key,
        "douyin::珩舟::two",
        {"author_name": "珩舟", "like_raw": "900", "caption": "two"},
    )

    with SessionLocal() as session:
        absorb(session, "douyin", apply=True)
        captions = sorted(post.caption for post in session.query(MODEL))
        assert captions == ["one", "two"]


def test_a_different_day_is_a_different_post(client, api_key):
    _capture(
        client,
        api_key,
        "douyin::珩舟::",
        {"author_name": "珩舟", "like_raw": "8"},
        when="2026-09-18T19:50:00Z",
    )
    _capture(
        client,
        api_key,
        "douyin::珩舟::#短发",
        {"author_name": "珩舟", "like_raw": "8", "caption": "#短发"},
    )

    with SessionLocal() as session:
        assert pairs(session, "douyin") == []
