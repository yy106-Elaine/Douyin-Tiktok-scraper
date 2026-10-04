"""The interview frame: one row per account, with what happened to their posts."""
from datetime import datetime, timedelta, timezone

import pytest

from app.interviews import candidates, frame

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session


def _check(session, video_id, when, alive, platform="douyin"):
    """One visit. `evidence` is the fact the fetch established.

    Douyin answers a request for a removed video with the next
    recommended one, so the id that came back is the signal.
    """
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED, SERVED_ANOTHER

    session.add(LinkCheck(
        platform=platform, video_id=video_id, target_kind="video",
        url=f"https://www.douyin.com/video/{video_id}",
        http_status=200,
        evidence=ID_CONFIRMED if alive else SERVED_ANOTHER,
        checked_at=when,
    ))


def _removed(session, video_id, sec_uid, platform="douyin", back=False):
    from app.models import AuthorPost, WebVideo

    session.add(WebVideo(platform=platform, video_id=video_id, sec_uid=None))
    session.add(AuthorPost(platform=platform, sec_uid=sec_uid, video_id=video_id))
    _check(session, video_id, NOW, True, platform)
    _check(session, video_id, NOW + timedelta(days=1), False, platform)
    if back:
        _check(session, video_id, NOW + timedelta(days=2), True, platform)


def _alive(session, video_id, sec_uid, platform="douyin"):
    from app.models import AuthorPost, WebVideo

    session.add(WebVideo(platform=platform, video_id=video_id, sec_uid=sec_uid))
    session.add(AuthorPost(platform=platform, sec_uid=sec_uid, video_id=video_id))
    _check(session, video_id, NOW, True, platform)


def _author(session, sec_uid, handle=None, error=None):
    from app.models import WebAuthor

    session.add(WebAuthor(
        platform="douyin", sec_uid=sec_uid, author_handle=handle,
        author_name="某人", error=error, http_status=200, fetched_at=NOW,
    ))


def test_an_account_with_a_removed_post_is_on_the_list(session):
    _removed(session, "7001", "SEC-a")
    _author(session, "SEC-a", handle="alice")
    session.commit()

    people = candidates(session, "douyin")

    assert len(people) == 1
    assert people[0].handle == "alice"
    assert people[0].profile_url.endswith("SEC-a")
    assert people[0].removed == 1


def test_an_account_with_nothing_removed_is_not(session):
    _alive(session, "7002", "SEC-b")
    _author(session, "SEC-b", handle="bob")
    session.commit()

    assert candidates(session, "douyin") == []


def test_every_removed_post_of_one_account_is_kept(session):
    """`kept_for_video_id` held one post per account and dropped the rest.

    That is wrong for exactly the accounts that matter most here: the
    ones with several posts taken down.
    """
    _removed(session, "7003", "SEC-c")
    _removed(session, "7004", "SEC-c")
    _removed(session, "7005", "SEC-c")
    _author(session, "SEC-c", handle="carol")
    session.commit()

    person = candidates(session, "douyin")[0]

    assert person.removed == 3
    assert {p.video_id for p in person.posts} == {"7003", "7004", "7005"}


def test_a_post_that_came_back_is_still_a_removal_here(session):
    _removed(session, "7006", "SEC-d", back=True)
    _author(session, "SEC-d", handle="dana")
    session.commit()

    person = candidates(session, "douyin")[0]

    assert person.removed == 1
    assert person.came_back == 1
    assert person.still_gone == 0
    assert "恢复" in person.note


def test_an_account_with_no_handle_says_why(session):
    _removed(session, "7007", "SEC-e")
    _author(session, "SEC-e", handle=None, error="served another profile")
    session.commit()

    person = candidates(session, "douyin")[0]

    assert person.reachable is False
    assert "served another profile" in person.note


def test_an_account_never_read_is_told_apart_from_one_that_is_gone(session):
    _removed(session, "7008", "SEC-f")
    session.commit()

    person = candidates(session, "douyin")[0]

    assert person.reachable is False
    assert "fetch_authors" in person.note


def test_the_frame_counts_what_the_tiles_show(session):
    _removed(session, "7009", "SEC-g")
    _removed(session, "7010", "SEC-h", back=True)
    _author(session, "SEC-g", handle="gail")
    _author(session, "SEC-h", handle=None, error="served another profile")
    session.commit()

    counted = frame(candidates(session, "douyin"))

    assert counted.accounts == 2
    assert counted.reachable == 1
    assert counted.unreachable == 1
    assert counted.removed_posts == 2
    assert counted.came_back_posts == 1


def test_图文_and_video_are_both_under_douyin(session):
    _removed(session, "7011", "SEC-i", platform="douyin_note")
    _author(session, "SEC-i", handle="iris")
    session.commit()

    people = candidates(session, "douyin")

    assert len(people) == 1
    assert people[0].posts[0].platform == "douyin_note"


def test_the_page_renders_with_the_account_and_its_posts(client, session):
    """A smoke test, because this page is read and not computed with."""
    _removed(session, "7012", "SEC-j")
    _removed(session, "7013", "SEC-j", back=True)
    _author(session, "SEC-j", handle="jane")
    session.commit()

    body = client.get("/dashboard/interviews?key=test-admin-key&platform=douyin").text

    assert "jane" in body
    assert "https://www.douyin.com/user/SEC-j" in body
    assert "7012" in body and "7013" in body
    # The sampling caveat is on the page, not left to be noticed.
    assert "No sampling yet" in body


def test_the_tab_is_on_every_page(client):
    body = client.get("/dashboard/overview?key=test-admin-key").text

    assert "/dashboard/interviews" in body
