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

    @property
    def is_gone(self) -> bool:
        return self.first_gone_at is not None

    @property
    def uncertainty(self) -> timedelta | None:
        """How wide the removal window is -- the schedule's precision."""
        if self.last_alive_at is None or self.first_gone_at is None:
            return None
        return self.first_gone_at - self.last_alive_at

    @property
    def published_at(self) -> datetime | None:
        return posted_at_from_video_id(self.video_id)

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


def _informative(checks: list[LinkCheck]) -> list[tuple[LinkCheck, str]]:
    graded = [(check, classify(check)) for check in checks]
    return [(check, verdict) for check, verdict in graded if verdict not in NO_INFORMATION]


def finding_for(checks: list[LinkCheck]) -> Finding | None:
    """Summarise one video's checks. `checks` must all be one video."""
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
    for check, verdict in graded:
        if verdict == ALIVE:
            # A video that came back resets the span: reinstatement is
            # a finding of its own, not a data error to smooth over.
            last_alive = check.checked_at
            first_gone = None
            outcome = None
        elif verdict in DISAPPEARED and first_gone is None:
            first_gone = check.checked_at
            # An account that is itself gone explains the video better
            # than the video's own page does.
            outcome = AUTHOR_GONE if AUTHOR_GONE in author_verdicts else verdict

    return Finding(
        video_id=first.video_id or "",
        platform=first.platform,
        author_handle=next(
            (check.author_handle for check in video_checks if check.author_handle), None
        ),
        url=first.url,
        checks=len(video_checks),
        uninformative=len(video_checks) - len(graded),
        first_checked_at=first.checked_at,
        last_checked_at=video_checks[-1].checked_at,
        last_alive_at=last_alive,
        first_gone_at=first_gone,
        current=graded[-1][1] if graded else None,
        outcome=outcome,
    )


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

    result = [f for checks in by_video.values() if (f := finding_for(checks))]
    result.sort(key=lambda finding: finding.last_checked_at or datetime.min, reverse=True)
    return result


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
