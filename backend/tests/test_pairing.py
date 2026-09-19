"""Pairing an actively shared link onto a passively captured post."""

from app.db import SessionLocal
from app.models import TikTokPost

_HEADERS_KEY = "X-API-Key"


def _capture(client, api_key, *, handle="someuser", at="2026-09-14T12:00:00Z",
             fingerprint="tiktok::someuser::hello"):
    return client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.zhiliaoapp.musically",
                    "fingerprint": fingerprint,
                    "captured_at": at,
                    "payload": {
                        "author_handle": handle,
                        "caption": "hello",
                        "like_raw": "10K",
                        "feed": "For You",
                    },
                }
            ],
        },
        headers={_HEADERS_KEY: api_key},
    )


def _share(client, api_key, text, at="2026-09-14T12:01:00Z"):
    return client.post(
        "/api/links/shared",
        json={"raw_text": text, "shared_at": at},
        headers={_HEADERS_KEY: api_key},
    )


def test_link_shared_shortly_after_capture_is_paired(client, api_key):
    _capture(client, api_key)
    response = _share(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7301234567890123456",
    )
    body = response.json()
    assert body["video_id"] == "7301234567890123456"
    assert body["paired_post_id"] is not None

    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id == "7301234567890123456"
        assert post.video_url == (
            "https://www.tiktok.com/@someuser/video/7301234567890123456"
        )


def test_author_mismatch_refuses_to_pair(client, api_key):
    _capture(client, api_key, handle="someuser")
    body = _share(
        client, api_key, "https://www.tiktok.com/@otheruser/video/7301234567890123456"
    ).json()
    assert body["paired_post_id"] is None

    with SessionLocal() as session:
        assert session.query(TikTokPost).one().video_id is None


def test_capture_outside_the_window_is_not_paired(client, api_key):
    _capture(client, api_key, at="2026-09-14T08:00:00Z")
    body = _share(
        client, api_key, "https://www.tiktok.com/@someuser/video/7301234567890123456"
    ).json()
    assert body["paired_post_id"] is None


def test_short_link_is_stored_but_flagged_for_resolution(client, api_key):
    _capture(client, api_key)
    body = _share(client, api_key, "7.86 复制打开抖音 https://v.douyin.com/iRkQwBt/ 复制").json()
    assert body["stored"] is True
    assert body["platform"] == "douyin"
    assert body["video_id"] is None
    assert body["needs_resolution"] is True
    assert body["paired_post_id"] is None


def test_text_with_no_link_is_rejected(client, api_key):
    assert _share(client, api_key, "no link here").status_code == 422


def test_nearest_capture_in_time_wins(client, api_key):
    _capture(client, api_key, at="2026-09-14T12:00:00Z", fingerprint="a")
    _capture(client, api_key, at="2026-09-14T12:10:00Z", fingerprint="b")
    body = _share(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7301234567890123456",
        at="2026-09-14T12:09:00Z",
    ).json()

    with SessionLocal() as session:
        paired = session.query(TikTokPost).filter(TikTokPost.video_id.isnot(None)).one()
        assert paired.id == body["paired_post_id"]
        assert paired.captured_at.isoformat() == "2026-09-14T12:10:00"


def _share_with_fingerprint(client, api_key, text, fingerprint, at):
    return client.post(
        "/api/links/shared",
        json={"raw_text": text, "shared_at": at, "fingerprint": fingerprint},
        headers={_HEADERS_KEY: api_key},
    )


def test_a_fingerprint_pairs_exactly_ignoring_the_time_window(client, api_key):
    # Captured hours before the link arrives: the window would refuse it.
    _capture(client, api_key, at="2026-09-14T02:00:00Z", fingerprint="fp-exact")
    body = _share_with_fingerprint(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7301234567890123456",
        "fp-exact",
        "2026-09-14T18:00:00Z",
    ).json()

    assert body["paired_post_id"] is not None
    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id == "7301234567890123456"


def test_a_fingerprint_pairs_despite_an_author_mismatch(client, api_key):
    # The device harvested this link from the post itself, so the
    # association is known; a handle read imperfectly off the screen
    # must not veto it.
    _capture(client, api_key, handle="someuser", fingerprint="fp-mismatch")
    body = _share_with_fingerprint(
        client,
        api_key,
        "https://www.tiktok.com/@different/video/7301234567890123456",
        "fp-mismatch",
        "2026-09-14T12:00:30Z",
    ).json()
    assert body["paired_post_id"] is not None


def test_the_pairing_method_is_recorded(client, api_key):
    from app.models import SharedLink

    _capture(client, api_key, fingerprint="fp-a")
    _share_with_fingerprint(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7301111111111111111",
        "fp-a",
        "2026-09-14T12:00:30Z",
    )
    _capture(client, api_key, fingerprint="fp-b", at="2026-09-14T13:00:00Z")
    _share(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7302222222222222222",
        at="2026-09-14T13:00:30Z",
    )

    with SessionLocal() as session:
        methods = {
            link.video_id: link.pairing_method
            for link in session.query(SharedLink).all()
        }
    assert methods["7301111111111111111"] == "fingerprint"
    assert methods["7302222222222222222"] == "window"


def test_an_unknown_fingerprint_falls_back_to_the_time_window(client, api_key):
    _capture(client, api_key, fingerprint="fp-real")
    body = _share_with_fingerprint(
        client,
        api_key,
        "https://www.tiktok.com/@someuser/video/7301234567890123456",
        "fp-never-captured",
        "2026-09-14T12:00:30Z",
    ).json()
    # Still paired, but by the heuristic, which analysis can exclude.
    assert body["paired_post_id"] is not None

    from app.models import SharedLink

    with SessionLocal() as session:
        assert session.query(SharedLink).one().pairing_method == "window"


class TestALinkNeverOverwritesAnother:
    """Two links carrying one fingerprint must not collapse onto a post.

    An assisted run produces exactly that. The device names the post it
    last read off the screen, and the capture buffer settles more slowly
    than the loop copies links, so several videos share one stale
    fingerprint. Before the guard, each link overwrote the previous one
    on the same post: five links, three reported "paired exactly", two
    posts holding an id, and whichever id was written last was the one
    that stuck -- a wrong video attributed to a caption, labelled exact.
    """

    def _capture(self, client, api_key, fingerprint, caption):
        response = client.post(
            "/api/captures/batch",
            json={
                "device_id": "pixel-7a",
                "captures": [
                    {
                        "platform_package": "com.ss.android.ugc.aweme",
                        "fingerprint": fingerprint,
                        "captured_at": "2026-09-19T02:09:00Z",
                        "payload": {"author_name": "someone", "caption": caption},
                    }
                ],
            },
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

    def _share(self, client, api_key, url, fingerprint):
        return client.post(
            "/api/links/shared",
            json={
                "raw_text": url,
                "shared_at": "2026-09-19T02:09:30Z",
                "fingerprint": fingerprint,
            },
            headers={"X-API-Key": api_key},
        )

    def test_the_first_id_wins_and_the_second_is_not_called_exact(
        self, client, api_key
    ):
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import DouyinPost, SharedLink

        self._capture(client, api_key, "douyin::someone::一", "一")
        self._share(client, api_key, "https://www.douyin.com/video/7686818714507271786", "douyin::someone::一")
        self._share(client, api_key, "https://www.douyin.com/video/7686847496509803195", "douyin::someone::一")

        with SessionLocal() as session:
            posts = list(session.scalars(select(DouyinPost)))
            links = list(session.scalars(select(SharedLink).order_by(SharedLink.id)))

        # The post keeps the id it was given first, not the last one in.
        assert [p.video_id for p in posts] == ["7686818714507271786"]
        assert links[0].pairing_method == "fingerprint"
        # The second link is not attached to that post as an exact match.
        assert links[1].pairing_method != "fingerprint" or (
            links[1].matched_capture_id != links[0].matched_capture_id
        )
