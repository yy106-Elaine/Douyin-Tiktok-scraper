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

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import local_date
from .platforms import family_members
from .clock import today as clock_today
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

    #: When the video became watchable again, for the most recent
    #: comeback: the check that found it alive after a disappearance.
    #: Not `last_alive_at`, which moves forward on every later check
    #: and so would report the same comeback as today's news every
    #: day for the rest of the study.
    came_back_at: datetime | None = None

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
    came_back_at: datetime | None = None
    for check, verdict in graded:
        if verdict == ALIVE:
            # Alive after a disappearance: this check is the comeback.
            if first_gone is not None:
                came_back_at = check.checked_at
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
        came_back_at=came_back_at,
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
        # A format shown under this platform is counted with it: see
        # platforms.MERGED_INTO. The rows keep their own platform, so
        # the two can still be told apart and compared.
        statement = statement.where(LinkCheck.platform.in_(family_members(platform)))

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

    "Came back today" means the check that found it alive again was
    made today -- not that it is alive today and was once gone. The
    first version asked the second question and so reported the same
    single comeback as news on every subsequent day, which is a state
    dressed up as an event.
    """
    # The researcher's day, not UTC's. Everything stored here is UTC,
    # which is right, but a Douyin pass run at 22:00 in Boston is
    # 02:00 the next day in UTC, so a UTC bucket filed last night's
    # removals under tomorrow and reported them twice-adjacent to a
    # day that had none. `clock` exists for exactly this boundary and
    # `views` already crosses it here; this function did not.
    when = local_date(day) if day is not None else clock_today()
    gone = sum(
        1
        for f in items
        if f.first_gone_at is not None and local_date(f.first_gone_at) == when
    )
    # Watchable now, and has a disappearance on record: the span was
    # reset by an alive check, so the check that reset it is the
    # reinstatement. Counted on the day that check was made.
    back = sum(
        1
        for f in items
        if f.came_back_at is not None and local_date(f.came_back_at) == when
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
    #: Counted here with the first sighting standing in for a missing
    #: publication time. See `horizon`.
    undated: int = 0

    @property
    def rate(self) -> float | None:
        measured = self.removed + self.survived
        return None if not measured else self.removed / measured

    @property
    def coverage(self) -> float | None:
        """Share of the eligible posts whose fate at `age` is known.

        The number that decides whether this rate may be read at all.
        A removal is known as soon as it happens; survival is only
        known once the post has been watched that long. So at an age
        the collection has barely reached, the removals are all in and
        almost none of the survivors are -- and the rate climbs toward
        100% for no reason but the calendar. Low coverage here means
        exactly that, and the number to show instead of the rate.
        """
        if not self.eligible:
            return None
        return (self.removed + self.survived) / self.eligible


def horizon(
    items: list["Finding"], age: timedelta, from_first_sighting: bool = False
) -> Horizon:
    """Share removed within `age` of publication. See `Horizon`.

    `from_first_sighting` dates a post with no publication time from
    the first time the study saw it instead of dropping it. That is a
    lower bound on its age -- it had already been posted when it was
    found -- so such a post can only be counted as surviving longer
    than it really did, never shorter. Douyin ids carry their own
    publication time, so this reaches the handful of rows whose id
    could not be read, and the count is reported rather than folded
    in silently.
    """
    out = Horizon(age=age)
    for finding in items:
        published = finding.published_at
        if published is None and from_first_sighting:
            published = finding.collected_at or finding.first_checked_at
            if published is not None:
                out.undated += 1
        if published is None:
            continue
        started = age_at_collection(finding)
        if started is None and from_first_sighting:
            # Dated from the first sighting, so by construction the
            # study was there from its (assumed) beginning.
            started = timedelta(0)
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


@dataclass
class Step:
    """One step of a survival curve: everything needed to read it."""

    #: Age since publication at which the step happens.
    age: timedelta
    #: Share of videos still up immediately after it.
    survival: float
    #: How many were under observation at that moment. A step taken
    #: over three videos is noise; the curve has to carry its own
    #: sample size or it invites being read as a finding.
    at_risk: int
    events: int


@dataclass
class Curve:
    """A Kaplan-Meier estimate, with the caveats it needs to be read."""

    steps: list[Step] = field(default_factory=list)
    #: Videos that contributed at all -- a publication time, and an
    #: observation window with some width to it.
    sample: int = 0
    events: int = 0
    #: Median width of the brackets behind the event times. Every age
    #: on the curve is uncertain by about this much.
    resolution: timedelta | None = None
    #: The oldest age anything was still being watched at. The curve
    #: is flat from its last step to here and undefined beyond it, so
    #: this is where it has to stop being drawn.
    watched_to: timedelta | None = None
    #: (entered, left) per video, in age since publication. Kept so
    #: the risk set can be counted at any age, not only at the ages
    #: where something happened -- which is what a "numbers at risk"
    #: row under the curve needs, and what tells a reader whether the
    #: tail rests on two posts or two hundred.
    windows: list[tuple[timedelta, timedelta]] = field(default_factory=list)

    def survival_at(self, age: timedelta) -> float | None:
        """Share still up at `age`, or None past the end of the curve."""
        if not self.steps:
            return None
        if age > self.steps[-1].age and self.steps[-1].survival > 0:
            # Beyond the last observation the estimate is undefined,
            # not flat: nothing was still being watched out there.
            return None
        current = 1.0
        for step in self.steps:
            if step.age > age:
                break
            current = step.survival
        return current

    def at_risk(self, age: timedelta) -> int:
        """How many videos were under observation at this age."""
        # Inclusive at both ends, so the column at age 0 reports the
        # whole sample rather than a zero -- a "numbers at risk" row
        # that starts at nothing reads as a bug.
        return sum(1 for start, end in self.windows if start <= age <= end)

    def quantile(self, share: float) -> timedelta | None:
        """Age by which `share` of videos are gone, or None if unreached.

        None is the honest answer far more often than a number is. A
        median needs the curve to cross 0.5, and a curve that never
        gets there has not measured a median -- it has measured that
        the median is longer than the study has run.
        """
        for step in self.steps:
            if step.survival <= 1 - share:
                return step.age
        return None


def _event_age(finding: "Finding") -> timedelta | None:
    """When a removal happened, as one number, from a bracket.

    The data says the video was alive at one check and gone at the
    next. The midpoint is the least-wrong single value to hand an
    estimator that wants one: taking the later check would date every
    removal to the schedule and shift the whole curve right by about
    half a cycle. `Curve.resolution` carries the width that this
    collapses, so the curve can be drawn with it rather than as if it
    were exact.
    """
    if finding.published_at is None or finding.first_gone_at is None:
        return None
    later = finding.first_gone_at
    earlier = finding.last_alive_at or finding.first_checked_at or later
    middle = earlier + (later - earlier) / 2
    return max(middle - finding.published_at, timedelta(0))


def kaplan_meier(items: list["Finding"]) -> Curve:
    """Survival since publication, with delayed entry.

    Two departures from a textbook call, both forced by how this
    sample is built:

    **Delayed entry.** A video joins the risk set when this study
    first saw it, not when it was published. Everything before that is
    unobserved, and treating it as observed survival is precisely the
    survivorship bias that makes a month-old TikTok sample look
    unkillable. So the risk set at age *t* is the videos whose
    collection age was below *t* and which were still being watched
    at it -- the left-truncated estimator, not the plain one.

    **Bracketed event times.** Each removal is known to within a
    checking cycle, and is placed at the middle of its bracket (see
    `_event_age`). The curve is therefore accurate to about
    `resolution`, which is reported with it.
    """
    entries: list[tuple[timedelta, timedelta, bool]] = []
    widths: list[timedelta] = []
    for finding in items:
        if finding.published_at is None:
            continue
        start = age_at_collection(finding)
        if start is None:
            continue
        if finding.is_gone:
            end = _event_age(finding)
            if end is None:  # pragma: no cover - guarded by is_gone
                continue
            span = finding.first_gone_at - (
                finding.last_alive_at or finding.first_checked_at
                or finding.first_gone_at
            )
            widths.append(span)
            event = True
        else:
            last = finding.last_checked_at
            if last is None:
                continue
            end = max(last - finding.published_at, timedelta(0))
            event = False
        if end <= start:
            # Nothing was observed about this video: it entered and
            # left at the same moment. It cannot inform any step.
            continue
        entries.append((start, end, event))

    curve = Curve(sample=len(entries))
    curve.windows = [(start, end) for start, end, _ in entries]
    if entries:
        curve.watched_to = max(end for _, end, _ in entries)
    moments = sorted({end for _, end, event in entries if event})
    alive = 1.0
    for moment in moments:
        at_risk = sum(
            1 for start, end, _ in entries if start < moment <= end
        )
        events = sum(
            1 for _, end, event in entries if event and end == moment
        )
        if not at_risk:  # pragma: no cover - events imply a risk set
            continue
        alive *= 1 - events / at_risk
        curve.steps.append(Step(moment, alive, at_risk, events))
        curve.events += events
    if widths:
        widths.sort()
        curve.resolution = widths[len(widths) // 2]
    return curve


def removal_ages(items: list["Finding"]) -> list[timedelta]:
    """How long each removed post lasted, among the removed ones.

    Sorted, one entry per post that has gone, measured from
    publication to the middle of the bracket it disappeared in.

    This is a description of the removals that have happened, and it
    is **not** an estimate of how long a post lasts. The posts that
    will be removed slowly have not been removed yet, so they are
    absent from this list, and the figure drifts upward the longer
    the study runs. `kaplan_meier` is the estimate that accounts for
    them; this is the answer to "the ones that were taken down -- how
    fast".
    """
    ages = [_event_age(f) for f in items if f.is_gone]
    return sorted(age for age in ages if age is not None)


def quartiles(
    spans: list[timedelta],
) -> tuple[timedelta, timedelta, timedelta] | None:
    """Lower quartile, median and upper quartile of a sorted list."""
    if not spans:
        return None

    def pick(share: float) -> timedelta:
        index = min(int(share * len(spans)), len(spans) - 1)
        return spans[index]

    return pick(0.25), pick(0.5), pick(0.75)
