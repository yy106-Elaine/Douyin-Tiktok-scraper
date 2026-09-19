"""The cleanup removes captures a parser bug made untrustworthy."""
from __future__ import annotations

from datetime import datetime

CUTOFF = datetime(2026, 9, 19, 2, 40)


def _capture(client, api_key, fingerprint, when):
    response = client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.ss.android.ugc.aweme",
                    "fingerprint": fingerprint,
                    "captured_at": when,
                    "payload": {"author_name": "someone", "caption": f"c {fingerprint}"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200


def _share(client, api_key, url, fingerprint, when):
    response = client.post(
        "/api/links/shared",
        json={"raw_text": url, "shared_at": when, "fingerprint": fingerprint},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200


def test_it_removes_only_what_predates_the_cutoff(client, api_key):
    from sqlalchemy import select

    from app.cleanup import purge, survey
    from app.db import SessionLocal
    from app.models import DouyinPost

    _capture(client, api_key, "old", "2026-09-19T02:09:00Z")
    _capture(client, api_key, "new", "2026-09-19T02:47:00Z")

    with SessionLocal() as session:
        assert survey(session, "douyin", CUTOFF)["posts"] == 1
        purge(session, "douyin", CUTOFF)
        remaining = list(session.scalars(select(DouyinPost)))

    assert [p.caption for p in remaining] == ["c new"]


def test_a_link_survives_with_its_id_and_loses_only_the_pairing(client, api_key):
    """The link was never the untrustworthy part.

    Its video id came from following a redirect, not from the parser.
    What goes is the claim that it belongs to a particular capture,
    because that capture is what was wrong.
    """
    from sqlalchemy import select

    from app.cleanup import purge
    from app.db import SessionLocal
    from app.models import SharedLink

    _capture(client, api_key, "old", "2026-09-19T02:09:00Z")
    _share(
        client,
        api_key,
        "https://www.douyin.com/video/7686818714507271786",
        "old",
        "2026-09-19T02:09:30Z",
    )

    with SessionLocal() as session:
        before = session.scalars(select(SharedLink)).one()
        assert before.pairing_method == "fingerprint"
        purge(session, "douyin", CUTOFF)

    with SessionLocal() as session:
        after = session.scalars(select(SharedLink)).one()

    assert after.video_id == "7686818714507271786"
    assert after.matched_capture_id is None
    assert after.pairing_method is None


def test_a_survey_changes_nothing(client, api_key):
    from sqlalchemy import func, select

    from app.cleanup import survey
    from app.db import SessionLocal
    from app.models import DouyinPost

    _capture(client, api_key, "old", "2026-09-19T02:09:00Z")
    with SessionLocal() as session:
        survey(session, "douyin", CUTOFF)
        assert session.scalar(select(func.count()).select_from(DouyinPost)) == 1
