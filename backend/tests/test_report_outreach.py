"""The two new panels: what Douyin said, and who to write to."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.fetch_videos import record_check
from app.recheck import API_FILTERED, SERVED_ANOTHER
from app.report import (
    REASON_GLOSS,
    WHY_CONTACT,
    hashtags_of,
    reasons_seen,
)


class _Page:
    http_status = 200
    error = None


def test_a_post_counts_once_however_often_it_was_checked(db: None) -> None:
    """One row per post, not per check.

    A post re-read on five days would otherwise count five times,
    and the commonest reason would be whichever posts were checked
    most rather than whichever reason Douyin gives most.
    """
    when = datetime(2026, 10, 14, 9, 0)
    with SessionLocal() as session:
        for day in range(5):
            check = record_check(
                session, "v1", _Page(), API_FILTERED,
                "https://www.douyin.com/video/v1", "douyin",
                filter_reason="status_self_see")
        record_check(session, "v2", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v2", "douyin",
                     filter_reason="status_deleted")

        counted = dict(reasons_seen(session))

    assert counted == {"status_self_see": 1, "status_deleted": 1}


def test_the_other_evidences_are_not_drawn_as_unknown(db: None) -> None:
    """They carry no reason, so a slice for them would be labelled
    "unknown" while really meaning "a different question was
    asked"."""
    with SessionLocal() as session:
        record_check(session, "v1", _Page(), SERVED_ANOTHER,
                     "https://www.douyin.com/video/v1", "douyin")
        assert reasons_seen(session) == []


def test_unstated_means_douyin_said_nothing(db: None) -> None:
    """"unstated" is what `filtered_out` returns when Douyin sends an
    empty reason. A null column is a different thing -- see
    test_a_reason_nobody_recorded_is_not_a_reason_nobody_gave."""
    from app.report import NOT_RECORDED

    with SessionLocal() as session:
        record_check(session, "v1", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v1", "douyin",
                     filter_reason="unstated")
        assert reasons_seen(session) == [("unstated", 1)]

        record_check(session, "v2", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v2", "douyin",
                     filter_reason=None)
        assert dict(reasons_seen(session))[NOT_RECORDED] == 1
    assert "no reason given" in REASON_GLOSS["unstated"]


def test_every_cell_has_a_reason_to_contact() -> None:
    """The four cells of the sampling frame, each with a sentence
    for the researcher's own notes -- never for the message."""
    from app.outreach import stratum_of
    from app.interviews import Candidate, Post

    def person(gone: int, back: int) -> Candidate:
        posts = [
            Post(video_id=f"g{i}", platform="douyin", caption=None,
                 published_at=None, first_gone_at=datetime(2026, 9, 1),
                 came_back_at=None, lifetime=None, gone=True, ever_gone=True)
            for i in range(gone)
        ] + [
            Post(video_id=f"b{i}", platform="douyin", caption=None,
                 published_at=None, first_gone_at=datetime(2026, 9, 1),
                 came_back_at=datetime(2026, 9, 5), lifetime=None,
                 gone=False, ever_gone=True)
            for i in range(back)
        ]
        return Candidate(sec_uid="a", handle="h", name=None, posts=posts)

    for gone, back in ((1, 0), (3, 0), (0, 1), (0, 2)):
        assert stratum_of(person(gone, back)) in WHY_CONTACT


def test_hashtags_come_off_a_caption() -> None:
    """Used to spread the recruiting across subject matter, not to
    classify anything -- the content coding does that later."""
    assert hashtags_of("好久不见 #wlw #拉拉日常 #les") == [
        "wlw", "拉拉日常", "les"]
    assert hashtags_of("#攻击性穿搭 #1 #wlw") == ["攻击性穿搭", "1", "wlw"]
    assert hashtags_of(None) == []
    assert hashtags_of("no tags here") == []


def test_the_contact_panel_is_off_unless_asked(db: None) -> None:
    """The page is otherwise safe to leave on a desk; with the list
    it names real people and links to their profiles."""
    from app.report import build

    with SessionLocal() as session:
        assert "访谈名单" not in build(session)


def test_the_panels_actually_render(db: None) -> None:
    """Build the page, not just the numbers behind it.

    The first version of this file tested `reasons_seen` and never
    rendered anything, so a wrong keyword in the `Slice` call passed
    every test and failed on her machine the moment she ran it. A
    panel is not covered until something has drawn it.
    """
    from datetime import datetime

    from app.models import AuthorPost, SharedLink, WebAuthor, WebVideo
    from app.report import build

    with SessionLocal() as session:
        session.add(SharedLink(
            participant_id="p1", platform="douyin", video_id="v1",
            raw_text="https://www.douyin.com/video/v1",
            canonical_url="https://www.douyin.com/video/v1",
            shared_at=datetime(2026, 10, 1)))
        session.add(WebVideo(
            platform="douyin", video_id="v1", sec_uid="acct",
            caption="好久不见 #wlw #拉拉日常",
            posted_on=datetime(2026, 10, 1)))
        session.add(AuthorPost(sec_uid="acct", video_id="v1",
                               platform="douyin"))
        session.add(WebAuthor(sec_uid="acct", author_handle="热拉xyz",
                              author_name="someone"))
        record_check(session, "v1", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/v1", "douyin",
                     filter_reason="status_audit_self_see")
        session.commit()

        with_list = build(session, outreach=True)
        without = build(session)

    # The reason panel draws, in both.
    assert "审核后仅自己可见" in with_list
    assert "审核后仅自己可见" in without
    # And the contact list only when asked for.
    assert "访谈名单" in with_list
    assert "访谈名单" not in without


def test_the_contact_links_are_live_and_the_list_is_open(db: None) -> None:
    """`table()` escapes every cell and hides it behind a closed
    <details>. That is right for the twin of a chart and wrong here:
    the links are the point, and a working list nobody can see
    without clicking is a list nobody works."""
    from app.report import contact_table

    drawn = contact_table(
        ["Who"],
        [['<a href="https://www.douyin.com/user/x">热拉xyz</a>']],
        "contact order")

    assert '<a href="https://www.douyin.com/user/x">' in drawn
    assert "<details" not in drawn


def test_a_reason_nobody_recorded_is_not_a_reason_nobody_gave(db: None) -> None:
    """The two look alike in a null column and mean opposite things.

    `filtered_out` returns the literal "unstated" when Douyin gives
    an empty reason, so that is a fact about Douyin. A null is this
    instrument not having stored anything -- true of every post found
    filtered before the column existed, which is the first hundred of
    them. Putting both in one wedge would report a gap in the
    collection as a finding about the platform.
    """
    from app.report import NOT_RECORDED, _why, reasons_seen

    with SessionLocal() as session:
        record_check(session, "old", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/old", "douyin",
                     filter_reason=None)
        record_check(session, "new", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/new", "douyin",
                     filter_reason="unstated")
        session.commit()

        counted = dict(reasons_seen(session))
        assert counted == {NOT_RECORDED: 1, "unstated": 1}

        drawn = _why(session, None)

    # The one Douyin would not explain is in the chart.
    assert "no reason given" in drawn
    # The one nobody wrote down is named, and said not to be that.
    assert "1 post(s) are not in this chart" in drawn
    assert 'not "none given"' in drawn


def test_the_panel_still_appears_when_nothing_has_a_reason_yet(db: None) -> None:
    """The state her collection is in right now: a hundred filtered
    posts, none of their reasons stored. A silent empty panel would
    read as "Douyin never refuses this way"."""
    from app.report import _why

    with SessionLocal() as session:
        record_check(session, "old", _Page(), API_FILTERED,
                     "https://www.douyin.com/video/old", "douyin",
                     filter_reason=None)
        session.commit()
        drawn = _why(session, None)

    assert "1 post(s) are not in this chart" in drawn


def test_every_tab_can_actually_be_opened() -> None:
    """A tab whose panel has no rule is a label you can click that
    shows nothing.

    The rules were written by hand for the two tabs that existed, so
    adding a third produced exactly that: a working tab strip above
    a blank page. They are generated from the panel list now, and
    this walks the list rather than naming the tabs, so a fourth
    cannot repeat it.
    """
    from app.report import tabs

    panels = [("overview", "A", "<p>a</p>"),
              ("analysis", "B", "<p>b</p>"),
              ("reach", "C", "<p>c</p>")]
    drawn = tabs(panels)

    for key, _, _ in panels:
        assert f"#tab-{key}:checked ~ .panel-{key} {{ display: block; }}" \
            in drawn
        assert f'<div class="panel-{key}">' in drawn
