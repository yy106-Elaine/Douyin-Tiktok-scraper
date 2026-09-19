"""Resolving a copied short link into a video id.

"Copy link" gives `v.douyin.com/XXXX` or `vm.tiktok.com/XXXX`: neither
carries the id, both redirect to a URL that does. The redirect follower
is injected, so this exercises the logic without the network.
"""

import urllib.error

from app.db import SessionLocal
from app.models import SharedLink, TikTokPost
from app.resolve import resolve_pending

_CAPTURE = {
    "platform_package": "com.zhiliaoapp.musically",
    "fingerprint": "fp-1",
    "captured_at": "2026-09-14T12:00:00Z",
    "payload": {"author_name": "someuser", "caption": "hello world"},
}


def _capture(client, api_key):
    return client.post(
        "/api/captures/batch",
        json={"device_id": "pixel-7a", "captures": [_CAPTURE]},
        headers={"X-API-Key": api_key},
    )


def _copy_link(client, api_key, text, fingerprint="fp-1"):
    return client.post(
        "/api/links/shared",
        json={
            "raw_text": text,
            "shared_at": "2026-09-14T12:00:30Z",
            "fingerprint": fingerprint,
        },
        headers={"X-API-Key": api_key},
    )


def test_a_short_link_resolves_and_pairs(client, api_key):
    _capture(client, api_key)
    body = _copy_link(
        client, api_key, "7.86 复制打开抖音 https://v.douyin.com/iRkQwBt/ 复制此链接"
    ).json()
    assert body["video_id"] is None
    assert body["needs_resolution"] is True

    def follower(url: str) -> str:
        assert url == "https://v.douyin.com/iRkQwBt/"
        return "https://www.douyin.com/video/7123456789012345678?extra=1"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.resolved == 1
    with SessionLocal() as session:
        link = session.query(SharedLink).one()
        assert link.video_id == "7123456789012345678"
        assert link.canonical_url == "https://www.douyin.com/video/7123456789012345678"


def test_resolution_reaches_the_captured_post(client, api_key):
    _capture(client, api_key)
    _copy_link(client, api_key, "https://vm.tiktok.com/ZMabc123/")

    def follower(_: str) -> str:
        return "https://www.tiktok.com/@someuser/video/7301234567890123456"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.paired == 1
    with SessionLocal() as session:
        post = session.query(TikTokPost).one()
        assert post.video_id == "7301234567890123456"
        assert post.video_url == (
            "https://www.tiktok.com/@someuser/video/7301234567890123456"
        )


def test_the_handle_from_a_resolved_url_is_kept(client, api_key):
    # The feed only shows a display name; the resolved URL carries the
    # handle, which is what makes an author contactable.
    _capture(client, api_key)
    _copy_link(client, api_key, "https://vm.tiktok.com/ZMabc123/")

    with SessionLocal() as session:
        resolve_pending(
            session,
            follower=lambda _: "https://www.tiktok.com/@realhandle/video/7301234567890123456",
            pause_seconds=0,
        )
        assert session.query(SharedLink).one().author_handle == "realhandle"


def test_an_unreachable_link_stays_pending(client, api_key):
    _copy_link(client, api_key, "https://v.douyin.com/broken/")

    def follower(_: str) -> str:
        raise urllib.error.URLError("no route to host")

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.failed == 1
    with SessionLocal() as session:
        # Left for the next run rather than written off.
        assert session.query(SharedLink).one().video_id is None


def test_a_redirect_that_yields_no_id_is_a_failure_not_a_wrong_id(client, api_key):
    _copy_link(client, api_key, "https://v.douyin.com/gone/")

    with SessionLocal() as session:
        report = resolve_pending(
            session,
            follower=lambda _: "https://www.douyin.com/?recommend=1",
            pause_seconds=0,
        )

    assert report.resolved == 0
    assert report.failed == 1


def test_already_resolved_links_are_not_refetched(client, api_key):
    _capture(client, api_key)
    _copy_link(
        client, api_key, "https://www.tiktok.com/@someuser/video/7301234567890123456"
    )

    calls = []

    with SessionLocal() as session:
        report = resolve_pending(
            session,
            follower=lambda url: calls.append(url) or url,
            pause_seconds=0,
        )

    assert calls == []
    assert report.attempted == 0


def test_each_link_reports_as_it_is_settled(client, api_key):
    """A run of a few hundred links is minutes long; silence reads as a hang."""
    _capture(client, api_key)
    _copy_link(client, api_key, "https://v.douyin.com/iRkQwBt/")
    _copy_link(client, api_key, "https://v.douyin.com/bad/", fingerprint="fp-2")

    def follower(url: str) -> str:
        if url.endswith("/bad/"):
            raise urllib.error.URLError("nope")
        return "https://www.douyin.com/video/7123456789012345678"

    seen: list[tuple[int, int, str]] = []
    with SessionLocal() as session:
        resolve_pending(
            session,
            follower=follower,
            pause_seconds=0,
            on_progress=lambda done, total, outcome: seen.append(
                (done, total, outcome)
            ),
        )

    assert [(done, total) for done, total, _ in seen] == [(1, 2), (2, 2)]
    assert "7123456789012345678" in seen[0][2]
    assert seen[1][2] == "could not be followed"


def test_a_repeated_id_is_refused_and_stops_the_pass(client, api_key):
    """Douyin answers a rate limit with a redirect, not a refusal.

    One pass wrote the same id to 130 rows: past some number of
    requests every short link landed on the same fallback page, and
    an id read off it looks exactly like a real one. Every share link
    names a different post, so the second sighting of an id is the
    signal that the answers have stopped meaning anything.
    """
    for number in range(8):
        _copy_link(
            client,
            api_key,
            f"https://v.douyin.com/link{number}/",
            fingerprint=f"fp-{number}",
        )

    followed: list[str] = []

    def follower(url: str) -> str:
        followed.append(url)
        if url.endswith("link0/"):
            return "https://www.iesdouyin.com/share/video/7686868494994886976/"
        # The fallback page, handed to everything after the limit.
        return "https://www.iesdouyin.com/share/video/7686345975925663411/"

    with SessionLocal() as session:
        report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert report.resolved == 2  # the real one, then the fallback once
    assert report.rate_limited is True
    # It stopped rather than working through the rest at one id each.
    assert len(followed) == 5

    with SessionLocal() as session:
        ids = [
            link.video_id
            for link in session.query(SharedLink).all()
            if link.video_id
        ]
        assert len(ids) == len(set(ids))


def test_repair_returns_duplicated_ids_to_pending(client, api_key):
    from app.resolve import unresolve_duplicates

    _capture(client, api_key)
    for number in range(3):
        _copy_link(
            client,
            api_key,
            f"https://v.douyin.com/link{number}/",
            fingerprint="fp-1" if number == 0 else f"fp-{number}",
        )

    # Simulate the damage the guard now prevents.
    with SessionLocal() as session:
        for link in session.query(SharedLink).all():
            link.video_id = "7686345975925663411"
        session.commit()

        assert unresolve_duplicates(session) == 3

        for link in session.query(SharedLink).all():
            assert link.video_id is None
            assert link.canonical_url is None
            assert link.matched_capture_id is None
        # And the copied text, which is the observation, is still there.
        assert all(link.raw_text for link in session.query(SharedLink).all())
