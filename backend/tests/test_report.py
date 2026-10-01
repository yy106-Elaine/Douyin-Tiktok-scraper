"""The standalone page: what it must show, and what it must not carry.

The page is meant to be mailed to an adviser, so two of these are
about privacy rather than about charts, and one is about the page
still being complete when the script does not run.
"""
from __future__ import annotations

from datetime import datetime

from app.db import SessionLocal
from app.models import LinkCheck, WebVideo
from app.report import Column, build, columns, mask

CAPTION = "姐妹 情侣 日常 这个人的脸 #wlw #长发t"
VIDEO_ID = "7512345678901234567"


def _check(session, video_id: str, when: datetime, alive: bool = True,
           platform: str = "douyin") -> None:
    session.add(
        LinkCheck(
            platform=platform,
            video_id=video_id,
            target_kind="video",
            url=f"https://www.douyin.com/video/{video_id}",
            http_status=200,
            evidence="id confirmed" if alive else "served another video",
            checked_at=when,
        )
    )


def _collection(session) -> None:
    _check(session, VIDEO_ID, datetime(2026, 9, 25, 18, 0))
    _check(session, VIDEO_ID, datetime(2026, 9, 26, 18, 0), alive=False)
    # The 27th is missing on purpose, and the 28th finds it back.
    _check(session, VIDEO_ID, datetime(2026, 9, 28, 18, 0))
    session.add(
        WebVideo(
            platform="douyin",
            video_id=VIDEO_ID,
            caption=CAPTION,
            author_handle="someone-real",
            fetched_at=datetime(2026, 9, 25, 18, 0),
        )
    )
    session.commit()


def test_the_page_carries_no_caption_and_no_whole_id(db: None) -> None:
    """A file that can be mailed is a file that can be forwarded.

    These are posts by identifiable people on a sensitive topic, and
    the removed ones are exactly the posts whose authors are most
    exposed. The aggregates say everything the page is for; the
    caption, the handle and the full id say who.
    """
    with SessionLocal() as session:
        _collection(session)
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert CAPTION not in page
    assert "someone-real" not in page
    assert VIDEO_ID not in page
    assert "…234567" in page  # the masked form, so rows stay tellable apart


def test_identifiers_are_opt_in(db: None) -> None:
    with SessionLocal() as session:
        _collection(session)
        page = build(session, reveal=True,
                     generated=datetime(2026, 10, 1, 2, 30))

    assert VIDEO_ID in page
    # Still no caption: the flag unmasks ids, it does not open the text.
    assert CAPTION not in page


def test_mask_keeps_rows_distinguishable() -> None:
    assert mask("7512345678901234567", reveal=False) == "…234567"
    assert mask("7512345678901234567", reveal=True) == "7512345678901234567"
    assert mask("123", reveal=False) == "123"


def test_every_chart_has_a_table_under_it(db: None) -> None:
    """Nothing on the page is reachable only by hovering.

    The hover layer is JavaScript; the tables are not. A reader with
    scripting off, a printout, or a screen reader gets every number.
    """
    with SessionLocal() as session:
        _collection(session)
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert page.count("<svg") >= 2
    # One per chart-bearing section, plus the context platforms' own.
    assert page.count("<table>") >= 3
    assert "Table —" in page


def test_the_stamp_is_the_researchers_clock(db: None) -> None:
    """02:30 UTC is the previous evening in New York.

    The dashboard shows local time everywhere. A page that dated
    itself a day ahead would make two outputs of the same run look
    like two different runs.
    """
    with SessionLocal() as session:
        _collection(session)
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert "2026-09-30 22:30" in page
    assert "2026-10-01 02:30" not in page


def test_an_unobserved_day_draws_a_break_and_an_observed_zero_draws_a_tick() -> None:
    """The one thing this chart exists to get right.

    A gap and a zero look identical in every default charting
    library, and they are the opposite of each other: one says the
    study did not look, the other says it looked and found nothing.
    """
    drawn = [
        Column("2026-09-26", value=2, at_risk=10, rate=0.2),
        Column(label="", gap=True),
        Column("2026-09-28", value=0, at_risk=8, rate=0.0),
    ]
    svg = columns(drawn, ident="t", title="t")

    assert "//" in svg
    assert 'class="zero"' in svg
    # The gap contributes no bar and no day label of its own.
    assert svg.count('class="bar"') == 1
    assert "09-28" in svg


def test_the_page_renders_when_nothing_has_been_collected(db: None) -> None:
    """An empty database is a legitimate state, not a crash.

    It is what a fresh clone has, and what the container running the
    tests has: the page has to come out saying zero rather than
    raising on an empty maximum.
    """
    with SessionLocal() as session:
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert page.startswith("<!doctype html>")
    assert "Takedown observatory" in page
    assert "not reached" in page


def test_the_tabs_work_without_javascript(db: None) -> None:
    """Switching view is navigation, and navigation should not need a script.

    The page's only script is the hover readout, and everything it
    shows is also in a table. Losing a tab strip is a worse failure,
    so it is a radio input and a sibling selector: keyboard focus and
    arrow keys for free, and with scripting off every panel simply
    shows at once.
    """
    with SessionLocal() as session:
        _collection(session)
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert 'class="tab-radio" type="radio"' in page
    assert 'id="tab-overview"' in page
    assert "#tab-overview:checked ~ .panel-overview" in page
    # The tab strip is markup, not something the script assembles.
    assert "tab-strip" in page.split("<script>")[0]


def test_a_tab_with_nothing_in_it_is_not_rendered(db: None) -> None:
    """An empty tab is a click that leads nowhere.

    On a database with no captions the content analysis has nothing to
    say, so there is one view and no strip at all.
    """
    with SessionLocal() as session:
        page = build(session, generated=datetime(2026, 10, 1, 2, 30))

    assert '<nav class="tab-strip">' not in page


def test_a_line_stops_where_its_own_collection_stops_supporting_it() -> None:
    """Two ways a counted share stops meaning what it says.

    These are the real numbers. 图文 at fourteen days is fifteen
    removals and no survivors at all, so the share reads 100%; at
    seven days it is fifteen removals against eight survivors, so it
    reads 65%. Both are counted and neither is about 抖音 -- 343 of
    the 366 notes are younger than seven days, so the posts that can
    answer are the ones that were taken down. An age is drawn only
    when posts have outlived it AND most of the eligible posts have
    reached it.
    """
    from app.report import Counted

    # (age, removed, answerable, unknown)
    note = Counted(name="图文 (note)", slot=2, points=[
        (1.0, 10, 213, 118),   # 203 survivors, most posts answered
        (2.0, 13, 110, 238),   # 97 survivors, but 238 posts too young
        (7.0, 15, 23, 343),    # the 65% point
        (14.0, 15, 15, 351),   # the 100% point
    ])
    assert [age for age, _, _, _ in note.shown] == [1.0]
    assert note.survivors(2.0) == 97
    # The dropped ages still exist and can still be read.
    assert note.share(7.0) is not None

    video = Counted(name="视频 (video)", slot=1, points=[
        (7.0, 40, 194, 46),
        (10.0, 46, 145, 95),
        (14.0, 47, 47, 193),
    ])
    assert [age for age, _, _, _ in video.shown] == [7.0, 10.0]


def test_the_page_says_in_counts_why_a_line_is_short() -> None:
    """A line that stops at a day looks like a bug on its own.

    The reason is a count -- how many posts have outlived each age --
    so the page prints that rather than a line drawn past where it
    means anything.
    """
    from app.report import Counted, _coverage

    html = _coverage([Counted(name="图文 (note)", slot=2, points=[
        (1.0, 10, 213, 118),
        (2.0, 13, 110, 238),
        (7.0, 15, 23, 343),
    ])], [1.0, 2.0, 7.0])

    assert "203 past 1d" in html
    assert "97 past 2d" in html
    assert "8 past 7d" in html
    assert "stops at 1d" in html


def test_the_chart_draws_only_what_it_can_answer_for() -> None:
    """No dashed continuation, no hollow dots, no "most that can be
    said so far": a line climbing to 65% is read as 65% whatever is
    written beside it."""
    from app.report import Counted, removal_chart

    svg = removal_chart([
        Counted(name="视频 (video)", slot=1, points=[
            (1.0, 12, 128, 0),
            (7.0, 40, 194, 46),
            (10.0, 46, 145, 95),
            (14.0, 47, 47, 193),
        ]),
        Counted(name="图文 (note)", slot=2, points=[
            (1.0, 10, 213, 118),
            (7.0, 15, 23, 343),
        ]),
    ], ident="t")

    assert "thin" not in svg
    assert "hollow" not in svg
    assert ">145</text>" in svg   # 视频 reaches ten days
    assert ">47</text>" not in svg
    assert ">23</text>" not in svg  # and 图文 does not reach seven
    assert "65%" not in svg
