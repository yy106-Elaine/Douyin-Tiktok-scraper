"""Turn a video's check history into a takedown finding.

One check says what a page looked like at one moment. A finding needs
the sequence: when the video was last seen alive, when it was first
seen gone, and therefore how long it lasted.

The central decision here is that **removal time is an interval, not a
point**. A video observed alive on Tuesday and gone on Thursday was
removed somewhere in between; nothing in the data says where. Reporting
Thursday as "the" removal time would present the checking schedule as
if it were a property of the platform. So every finding carries
`last_alive_at`, `first_gone_at` and the width between them, and a
write-up quotes the bracket.

Verdicts that carry no information (a network failure, a bot
challenge, wording nothing recognises) are skipped rather than counted
as either outcome. They are reported separately, because a large
unknown count means the survival numbers are not yet trustworthy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LinkCheck
from .recheck import (
    ALIVE,
    AUTHOR_GONE,
    GONE,
    NO_INFORMATION,
    WITHHELD,
    classify,
)
from .snowflake import posted_at_from_video_id

#: Verdicts that mean the video could not be watched. Kept distinct in
#: the data -- an account that vanished is a different event from one
#: video being pulled -- but all three end a survival span.
DISAPPEARED = frozenset({GONE, AUTHOR_GONE, WITHHELD})


@dataclass
class Finding:
    """What the check history says about one video."""

    video_id: str
    platform: str
    author_handle: str | None
    url: str | None

    checks: int
    #: Checks that told us nothing. High counts invalidate the rest.
    uninformative: int

    first_checked_at: datetime | None
    last_checked_at: datetime | None
    #: Latest check that found it watchable.
    last_alive_at: datetime | None
    #: Earliest check, after that, which found it gone.
    first_gone_at: datetime | None
    #: The verdict of the most recent informative check.
    current: str | None
    #: The specific disappearance verdict, once it has disappeared.
    outcome: str | None

    #: When the video was published. Decoded from the id where the id
    #: encodes it (Douyin, TikTok -- see snowflake.py), otherwise taken
    #: from the collected post row, which is where YouTube's exact
    #: publishedAt lives. Without the second source this column, and
    #: every lifetime computed from it, was empty for YouTube.
    published_at: datetime | None = None

    #: When this study first saw the video -- the earliest capture of
    #: it, which is also an observation that it was watchable then.
    #: Watching starts here, not at the first re-check, and a removal
    #: before it was never observable. See `age_at_collection`.
    collected_at: datetime | None = None

    #: How many times this video has been found gone, including
    #: spells it came back from. Without it a reinstated video is
    #: indistinguishable from one that was never touched.
    disappearances: int = 0

    #: The earliest disappearance ever recorded, kept whatever
    #: happened afterwards. `first_gone_at` is reset by a later alive
    #: check, which is right for "is it gone now" and wrong for the
    #: table: a video that came back showed an empty First gone
    #: column, so the removal it had survived was invisible on the
    #: page that exists to show removals.
    first_gone_ever: datetime | None = None

    @property
    def came_back(self) -> bool:
        """Found gone at some point, and watchable at the last check."""
        return bool(self.disappearances) and not self.is_gone

    #: Requests that could not have seen anything -- see `_blind`.
    #: Recorded, and excluded from `checks` and `uninformative`, so a
    #: fetcher that cannot read a platform does not read as a platform
    #: that cannot be measured.
    blind: int = 0

    @property
    def is_gone(self) -> bool:
        return self.first_gone_at is not None

    @property
    def uncertainty(self) -> timedelta | None:
        """How wide the removal window is -- the schedule's precision."""
        if self.last_alive_at is None or self.first_gone_at is None:
            return None
        return self.first_gone_at - self.last_alive_at

    def lifetime(self) -> tuple[timedelta, timedelta] | None:
        """Time from publication to removal, as (at least, at most).

        Two bounds because both ends are intervals: publication is
        known exactly from the id, but removal only to within the gap
        between checks.
        """
        published = self.published_at
        if published is None or not self.is_gone:
            return None
        assert self.first_gone_at is not None
        lower = (self.last_alive_at or published) - published
        upper = self.first_gone_at - published
        return max(lower, timedelta(0)), max(upper, timedelta(0))


def _blind(check: LinkCheck) -> bool:
    """A check that could not have seen anything, however it went.

    douyin.com answers a request with no session with a JavaScript
    shell: HTTP 200, no error, nothing about the video. A round of
    those is not a round of failed observations -- it is a round of
    observations never attempted, by a fetcher that cannot read this
    platform. One sweep wrote 202 of them.

    They stay on file; every request made is on file. What they must
    not do is count against the finding. `summarise` calls a video
    doubtful once more than half its checks told us nothing, which is
    the right warning about a flaky site and the wrong one here: it
    marked all 177 Douyin videos doubtful on noise this study
    generated itself, including the ones whose removal the browser
    pass had confirmed.

    Identified by construction rather than by platform alone, so a
    Douyin check that did read something -- a 404, a removal notice,
    a verified id -- still counts for everything.
    """
    from .recheck import BROWSER_ONLY

    if check.platform not in BROWSER_ONLY:
        return False
    if check.evidence or check.error:
        return False
    return check.http_status == 200


def _informative(checks: list[LinkCheck]) -> list[tuple[LinkCheck, str]]:
    graded = [(check, classify(check)) for check in checks]
    return [(check, verdict) for check, verdict in graded if verdict not in NO_INFORMATION]


def finding_for(
    checks: list[LinkCheck],
    posted_on: datetime | None = None,
    collected_at: datetime | None = None,
) -> Finding | None:
    """Summarise one video's checks. `checks` must all be one video.

    `posted_on` is the publication time recorded when the video was
    collected, used when the id does not encode one. `collected_at`
    is when it was first collected, which is when watching began.
    """
    video_checks = [check for check in checks if check.target_kind == "video"]
    if not video_checks:
        return None
    video_checks.sort(key=lambda check: check.checked_at)
    first = video_checks[0]

    graded = _informative(video_checks)
    author_verdicts = {
        classify(check) for check in checks if check.target_kind == "author"
    }

    last_alive: datetime | None = None
    first_gone: datetime | None = None
    outcome: str | None = None
    disappearances = 0
    first_gone_ever: datetime | None = None
    for check, verdict in graded:
        if verdict == ALIVE:
            # A video that came back resets the span: reinstatement is
            # a finding of its own, not a data error to smooth over.
            last_alive = check.checked_at
            first_gone = None
            outcome = None
        elif verdict in DISAPPEARED and first_gone is None:
            first_gone = check.checked_at
            disappearances += 1
            if first_gone_ever is None:
                first_gone_ever = check.checked_at
            # An account that is itself gone explains the video better
            # than the video's own page does.
            outcome = AUTHOR_GONE if AUTHOR_GONE in author_verdicts else verdict

    blind = sum(1 for check in video_checks if _blind(check))
    return Finding(
        video_id=first.video_id or "",
        platform=first.platform,
        author_handle=next(
            (check.author_handle for check in video_checks if check.author_handle), None
        ),
        url=first.url,
        checks=len(video_checks) - blind,
        uninformative=len(video_checks) - len(graded) - blind,
        blind=blind,
        first_checked_at=first.checked_at,
        last_checked_at=video_checks[-1].checked_at,
        last_alive_at=last_alive,
        first_gone_at=first_gone,
        current=graded[-1][1] if graded else None,
        outcome=outcome,
        published_at=posted_at_from_video_id(first.video_id) or posted_on,
        collected_at=collected_at,
        disappearances=disappearances,
        first_gone_ever=first_gone_ever,
    )


def _collected_by_video(session: Session, platform: str | None) -> dict[str, datetime]:
    """Earliest capture of each video, keyed by video id.

    The moment watching began. A capture is itself a sighting of a
    watchable video, so it is the left edge of every survival span --
    and a removal before it could not have been seen from here. See
    `age_at_collection`.
    """
    from .parsers import PLATFORM_TABLES

    names = [platform] if platform else list(PLATFORM_TABLES)
    out: dict[str, datetime] = {}
    for name in names:
        registered = PLATFORM_TABLES.get(name)
        if registered is None:
            continue
        model, _ = registered
        for video_id, captured_at in session.execute(
            select(model.video_id, model.captured_at).where(model.video_id.isnot(None))
        ):
            if captured_at is None:
                continue
            held = out.get(video_id)
            if held is None or captured_at < held:
                out[video_id] = captured_at

    # A link carries a sighting too, and on TikTok most ids arrive
    # that way: the video was on screen when its link was copied.
    from .models import SharedLink

    for video_id, shared_at in session.execute(
        select(SharedLink.video_id, SharedLink.shared_at).where(
            SharedLink.video_id.isnot(None),
            *([SharedLink.platform == platform] if platform else []),
        )
    ):
        if shared_at is None:
            continue
        held = out.get(video_id)
        if held is None or shared_at < held:
            out[video_id] = shared_at
    return out


def _published_by_video(session: Session, platform: str | None) -> dict[str, datetime]:
    """Publication times from the collected rows, keyed by video id.

    Only needed for platforms whose ids carry no timestamp, but looked
    up for all of them so nothing depends on which platform this is.
    """
    from .parsers import PLATFORM_TABLES

    names = [platform] if platform else list(PLATFORM_TABLES)
    out: dict[str, datetime] = {}
    for name in names:
        registered = PLATFORM_TABLES.get(name)
        if registered is None:
            continue
        model, _ = registered
        for video_id, posted_on in session.execute(
            select(model.video_id, model.posted_on).where(
                model.video_id.isnot(None), model.posted_on.isnot(None)
            )
        ):
            out.setdefault(video_id, posted_on)
    return out


def findings(session: Session, platform: str | None = None) -> list[Finding]:
    """One finding per checked video, most recently checked first."""
    statement = select(LinkCheck).order_by(LinkCheck.checked_at)
    if platform:
        statement = statement.where(LinkCheck.platform == platform)

    by_video: dict[str, list[LinkCheck]] = {}
    orphan_authors: list[LinkCheck] = []
    for check in session.scalars(statement):
        if check.video_id:
            by_video.setdefault(check.video_id, []).append(check)
        else:
            orphan_authors.append(check)

    # An author check is stored without a video id, so hand it to every
    # video of that author -- that is the video it was made for.
    for check in orphan_authors:
        if not check.author_handle:
            continue
        for checks in by_video.values():
            if any(
                other.author_handle == check.author_handle
                for other in checks
                if other.target_kind == "video"
            ):
                checks.append(check)

    published = _published_by_video(session, platform)
    collected = _collected_by_video(session, platform)
    result = [
        f
        for video_id, checks in by_video.items()
        if (f := finding_for(checks, published.get(video_id), collected.get(video_id)))
    ]
    result.sort(key=lambda finding: finding.last_checked_at or datetime.min, reverse=True)
    return result



def today_at_a_glance(
    items: list["Finding"], day: "datetime | None" = None
) -> tuple[int, int]:
    """(first found gone today, back today) over these findings.

    Both numbers are the day's news, and neither is in the run
    report: a pass prints how many videos are gone *now*, which is a
    running total. Reading the day's change out of it means
    remembering yesterday's number and subtracting -- and a number
    that has to be copied by hand every day is a number that will
    eventually be wrong, on the study's main result.

    A video that came back is counted from the same history, because
    `finding_for` already resets the span when a check finds it alive
    again. That is not a correction to smooth over: an appeal that
    succeeded and a block that was lifted are findings, and the day
    a running total goes *down* is the day they happened.
    """
    when = (day or datetime.utcnow()).date()
    gone = sum(
        1
        for f in items
        if f.first_gone_at is not None and f.first_gone_at.date() == when
    )
    # Watchable now, and has a disappearance on record: the span was
    # reset by an alive check, so the check that reset it is the
    # reinstatement. Counted on the day that check was made.
    back = sum(
        1
        for f in items
        if f.came_back
        and f.last_alive_at is not None
        and f.last_alive_at.date() == when
    )
    return gone, back

@dataclass
class Summary:
    tracked: int = 0
    gone: int = 0
    alive: int = 0
    #: Videos whose latest informative check is missing entirely.
    unmeasured: int = 0
    #: Videos where more than half the checks told us nothing.
    doubtful: int = 0
    #: Median width of the removal windows -- the schedule's precision,
    #: reported so a lifetime is never quoted more precisely than the
    #: checking cadence supports.
    median_uncertainty: timedelta | None = None

    @property
    def rate(self) -> float | None:
        """Share of *measured* videos that disappeared.

        Unmeasured videos are excluded from the denominator rather than
        assumed alive: a video we could never reach is not evidence
        either way, and folding it in biases the rate downward.
        """
        measured = self.gone + self.alive
        return None if not measured else self.gone / measured


def summarise(items: list[Finding]) -> Summary:
    summary = Summary(tracked=len(items))
    widths = []
    for finding in items:
        if finding.current is None:
            summary.unmeasured += 1
        elif finding.is_gone:
            summary.gone += 1
        else:
            summary.alive += 1
        if finding.checks and finding.uninformative * 2 > finding.checks:
            summary.doubtful += 1
        if (width := finding.uncertainty) is not None:
            widths.append(width)

    if widths:
        widths.sort()
        summary.median_uncertainty = widths[len(widths) // 2]
    return summary


# --------------------------------------------------------------------
# How old a video was when we started watching it
# --------------------------------------------------------------------
#
# A removal that happened before the first sighting is not a removal
# this study missed -- it is one this study could never have seen. A
# TikTok search for a month-old phrase returns the videos that lasted
# a month; the ones pulled on day one are absent from the results, not
# present and alive. Pooling those with Douyin rows collected hours
# after posting produces a rate that is mostly a statement about which
# search was run.
#
# So two things are recorded. `age_at_collection` says how much of a
# video's life had already happened before anyone here looked, and
# `horizon` answers "removed within T of publication?" using only the
# videos that were being watched before age T -- the rest are not
# counted as survivors, they are left out, because for them the
# question has no answer.


def age_at_collection(finding: "Finding") -> timedelta | None:
    """How old the video already was when this study first saw it."""
    if finding.published_at is None:
        return None
    started = finding.collected_at or finding.first_checked_at
    if started is None:
        return None
    return max(started - finding.published_at, timedelta(0))


#: Upper edge of each band, and its label. Open-ended at the top.
AGE_BANDS: tuple[tuple[timedelta | None, str], ...] = (
    (timedelta(days=1), "under a day old"),
    (timedelta(days=3), "1-3 days old"),
    (timedelta(days=7), "3-7 days old"),
    (timedelta(days=30), "1-4 weeks old"),
    (None, "over a month old"),
)

UNDATED_BAND = "publication time unknown"


def band_for(age: timedelta | None) -> str:
    if age is None:
        return UNDATED_BAND
    for edge, label in AGE_BANDS:
        if edge is None or age < edge:
            return label
    return AGE_BANDS[-1][1]


def by_collection_age(items: list["Finding"]) -> list[tuple[str, "Summary"]]:
    """The corpus split by how fresh each video was when collected.

    In band order, and only the bands that have anything in them: an
    empty row invites a reader to compare a rate against nothing.
    """
    grouped: dict[str, list[Finding]] = {}
    for finding in items:
        grouped.setdefault(band_for(age_at_collection(finding)), []).append(finding)
    order = [label for _, label in AGE_BANDS] + [UNDATED_BAND]
    return [(label, summarise(grouped[label])) for label in order if label in grouped]


@dataclass
class Horizon:
    """Removals within `age` of publication, among videos watched that early.

    `eligible` is the population the question can be asked of: a
    publication time is known and the first sighting came before
    `age`. A video first seen at three weeks is not a survivor of its
    first three days; nothing was watching then, so it is left out
    rather than counted alive.

    `censored` is the other exclusion, at the far end: still watchable
    at the last check, but that check came before `age`. Its fate at
    `age` is simply not known yet, so it is out of the denominator too
    and reported, because a large number here means the rate is early
    rather than low.
    """

    age: timedelta
    eligible: int = 0
    removed: int = 0
    survived: int = 0
    censored: int = 0
    #: Removed, but the check that found it gone was late enough that
    #: the removal might have fallen after `age`. Counted as removed
    #: -- the alternative is to drop the very events being measured --
    #: and reported so the rate's precision is visible.
    bracketed: int = 0

    @property
    def rate(self) -> float | None:
        measured = self.removed + self.survived
        return None if not measured else self.removed / measured


def horizon(items: list["Finding"], age: timedelta) -> Horizon:
    """Share removed within `age` of publication. See `Horizon`."""
    out = Horizon(age=age)
    for finding in items:
        published = finding.published_at
        if published is None:
            continue
        started = age_at_collection(finding)
        if started is None or started >= age:
            # Not watched early enough for this question.
            continue
        out.eligible += 1
        if finding.is_gone:
            assert finding.first_gone_at is not None
            if finding.first_gone_at - published <= age:
                out.removed += 1
                if (
                    finding.last_alive_at is not None
                    and finding.last_alive_at - published > age
                ):  # pragma: no cover - ordering makes this unreachable
                    out.bracketed += 1
            elif (
                finding.last_alive_at is not None
                and finding.last_alive_at - published <= age
            ):
                # Gone, but only seen gone after the horizon, and the
                # last sighting alive was before it: the removal
                # bracket straddles `age`.
                out.removed += 1
                out.bracketed += 1
            else:
                out.survived += 1
        elif (
            finding.last_checked_at is not None
            and finding.last_checked_at - published >= age
        ):
            out.survived += 1
        else:
            out.censored += 1
    return out
