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


def test_the_counted_curve_thins_rather_than_stopping() -> None:
    """Counting is honest at every age but not unbiased at every age.

    A post removed on day two is known at every later age; a surviving
    post has to be watched that long to count at all. So the known set
    fills up with removals and the share drifts towards 100%. Dropping
    those ages outright cut 图文, collected in one recent burst, back
    to a single day -- a format watched for a week reading as if it had
    been watched for a day. So the thin ages are drawn dashed and
    marked thin instead, and only a denominator too small to mean
    anything leaves the chart.
    """
    from app.report import Counted

    line = Counted(name="video", slot=1, points=[
        (1.0, 5, 100, 10),    # most fates known -- solid
        (7.0, 20, 60, 40),    # still more known than not -- solid
        (14.0, 19, 19, 80),   # only the removed ones are known -- dashed
        (30.0, 2, 2, 90),     # two posts cannot carry a point -- gone
    ])

    assert [age for age, _, _, _ in line.shown] == [1.0, 7.0, 14.0]
    assert [line.firm(age) for age, _, _, _ in line.shown] == [
        True, True, False]
    assert line.reach == 14.0
    # The dropped point still exists and can still be read.
    assert line.share(30.0) == 1.0
    assert line.answerable(30.0) == 2


def test_a_thin_stretch_is_drawn_dashed_and_hollow() -> None:
    """The reader has to be able to see where the support runs out.

    Colour alone would not carry it and a footnote would not be read
    at the point of looking, so the line itself changes: dashed from
    the last well-supported age onwards, with hollow dots.
    """
    from app.report import Counted, removal_chart

    svg = removal_chart([Counted(name="图文 (note)", slot=2, points=[
        (1.0, 10, 90, 20),
        (3.0, 14, 50, 45),
        (7.0, 18, 30, 70),
        (10.0, 20, 21, 95),
    ])], ident="t")

    assert 'class="line c2"' in svg       # the firm stretch
    assert 'class="line thin c2"' in svg  # and the thin one
    assert "hollow" in svg
    # Nothing was dropped: every age still prints its denominator.
    for count in ("90", "50", "30", "21"):
        assert f">{count}</text>" in svg
