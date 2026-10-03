"""The 抖音号 is collected in the pass that reads the post.

Not in a pass of its own, days later. The handle is the only field
that finds an account again, an interview request is addressed to it,
and a removed post's row no longer carries its author -- so the visit
has to happen while the post is still in hand.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.daily import authors, one
from app.fetch_videos import SITES
from app.models import WebAuthor
from app.pagedata import Fetched

SEC_UID = "MS4wLjABAAAA-alice"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 60_000


@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session


def _video(
    video_id: str,
    caption: str = "#lwl 今天",
    sec_uid: str = SEC_UID,
    shown_handle: str = "",
) -> Fetched:
    """A video page's own record of its author.

    `shown_handle` is empty by default because that is what Douyin's
    video payload usually carries: a display name and an account id,
    no 抖音号. That absence is the whole reason for the profile visit.
    """
    return Fetched(
        url="x",
        html="",
        http_status=200,
        payloads=[{
            "aweme_id": video_id,
            "desc": caption,
            "create_time": 1_758_000_000,
            "author": {
                "nickname": "某人",
                "unique_id": shown_handle,
                "sec_uid": sec_uid,
            },
            "statistics": {"digg_count": 1, "comment_count": 0, "share_count": 0},
            "video": {"play_addr": {"url_list": ["https://cdn.example/v.mp4"]}},
        }],
    )


def _profile(sec_uid: str = SEC_UID, handle: str = "alice_real") -> Fetched:
    return Fetched(
        url="p",
        html="",
        http_status=200,
        payloads=[{
            "sec_uid": sec_uid,
            "nickname": "某人",
            "unique_id": handle,
            "follower_count": 120,
        }],
    )


def _hook(session, visited, page=None):
    def read_profile(sec_uid: str) -> Fetched:
        visited.append(sec_uid)
        return page or _profile(sec_uid)

    return authors(session, read_profile)


def test_a_kept_post_has_its_author_read_in_the_same_pass(session, tmp_path):
    visited: list[str] = []
    outcome, said, _ = one(
        session,
        read=lambda url: _video("7686773732988082810"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082810",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(session, visited),
    )

    assert visited == [SEC_UID]
    assert outcome == "saved"
    row = session.scalars(select(WebAuthor).where(WebAuthor.sec_uid == SEC_UID)).one()
    assert row.author_handle == "alice_real"


def test_a_post_the_filter_excludes_costs_no_profile_reading(session, tmp_path):
    """A profile reading is personal data about someone not in the study.

    `周小闹（纯闹）` is how this was noticed: the author pass read the
    profile of an account whose only post the topic filter excludes.
    """
    visited: list[str] = []
    outcome, said, _ = one(
        session,
        read=lambda url: _video("7686773732988082811", caption="#ootd 穿搭"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082811",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(session, visited),
    )

    assert visited == []
    assert "not kept" in said
    assert session.scalars(select(WebAuthor)).all() == []


def test_an_account_already_on_file_is_not_read_again(session, tmp_path):
    session.add(WebAuthor(sec_uid=SEC_UID, platform="douyin", author_handle="alice_real"))
    session.commit()

    visited: list[str] = []
    one(
        session,
        read=lambda url: _video("7686773732988082812"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082812",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(session, visited),
    )

    assert visited == []


def test_the_author_of_a_post_found_gone_is_still_read(session, tmp_path):
    """The whole reason the handle matters.

    A removal clears the row's author fields, so by the time a pass of
    its own came round there was nothing left to visit. The account is
    read here, out of what was on file before the row was emptied.
    """
    from app.fetch_videos import store

    page = _video("7686773732988082813")
    facts = SITES["douyin"].facts("", page.payloads)
    store(session, "7686773732988082813", page, facts, "douyin")

    visited: list[str] = []
    outcome, said, _ = one(
        session,
        read=lambda url: _video("9999999999999999999", sec_uid="MS4wLjABAAAA-stranger"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082813",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(session, visited),
    )

    assert outcome == "gone"
    assert visited == [SEC_UID]
    row = session.scalars(select(WebAuthor).where(WebAuthor.sec_uid == SEC_UID)).one()
    assert row.author_handle == "alice_real"


def test_a_profile_that_answers_for_somebody_else_is_not_believed(session, tmp_path):
    """A wrong handle is worse than none: an empty field is visibly empty."""
    visited: list[str] = []
    one(
        session,
        read=lambda url: _video("7686773732988082814"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082814",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(
            session, visited,
            page=_profile(sec_uid="MS4wLjABAAAA-stranger", handle="not_alice"),
        ),
    )

    row = session.scalars(select(WebAuthor).where(WebAuthor.sec_uid == SEC_UID)).one()
    assert row.author_handle is None
    assert row.error == "served another profile"


def test_a_handle_the_video_page_already_gave_costs_no_visit(session, tmp_path):
    """Douyin's video payload sometimes carries `unique_id` itself.

    When it does, that *is* the 抖音号 and there is nothing on the
    profile to go and get -- one request fewer against a site that
    counts them.
    """
    visited: list[str] = []
    one(
        session,
        read=lambda url: _video("7686773732988082815", shown_handle="alice_real"),
        download=lambda address, referer: (MP4, 200),
        video_id="7686773732988082815",
        site=SITES["douyin"],
        handle=None,
        directory=tmp_path,
        author=_hook(session, visited),
    )

    assert visited == []
