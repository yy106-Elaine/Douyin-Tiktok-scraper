"""How often a recorded removal was taken back, by the day it was recorded.

    ./.venv/bin/python -m app.recanted --platform douyin
    ./.venv/bin/python -m app.recanted --platform douyin_note --days 40

A check that says GONE is the study's finding. A later check on the
same post that says ALIVE is the instrument saying it was wrong, or
Douyin putting the post back; from the outside those look the same,
and the honest name for the pair is a *recanted* removal.

Reinstatement is real and this study measures it (METHODOLOGY 14e).
What is not plausible is fifty of them inside half an hour. So the
number worth watching is not how many came back but **what share of
one day's removals later came back** -- and whether that share
tracks a change in the instrument rather than anything about the
platform.

The question this was written for: from 10-06 to 10-14 the pass
blocked the page's own images, and on the video platform the daily
removal hazard went from 2-8% to 20-34%, with large batches
"returning" minutes apart afterwards. If `light` only *hid* posts
that would be recorded as unknown, the recant share should be flat
across the window. If it also made pages serve a different video --
which is the exact evidence `SERVED_ANOTHER` reads as a removal --
the share should rise with it, and the removals of those days
cannot be trusted.

Read-only, and it answers with a table rather than a verdict.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as utc_now
from .models import LinkCheck
from .recheck import ID_CONFIRMED, PAGE_SAYS_GONE, SERVED_ANOTHER

#: The two ways a check can say "gone", kept apart because they are
#: different claims. `PAGE_SAYS_GONE` is Douyin's own wording and is
#: hard to produce by accident; `SERVED_ANOTHER` is inferred from the
#: record that came back belonging to a different video, which is
#: exactly what a page that failed to load its own content and fell
#: through to a recommendation would also do.
GONE_EVIDENCE = (SERVED_ANOTHER, PAGE_SAYS_GONE)


@dataclass
class Day:
    """One day's removals, and what later became of them."""

    day: str
    said_gone: int = 0
    recanted: int = 0
    #: Split by which evidence the removal rested on.
    by_evidence: dict[str, int] = field(default_factory=dict)
    recanted_by_evidence: dict[str, int] = field(default_factory=dict)

    @property
    def share(self) -> float:
        return self.recanted / self.said_gone if self.said_gone else 0.0


def recanted_by_day(session: Session, platform: str,
                    since: datetime) -> list[Day]:
    """For each day, the removals recorded then that a later check undid.

    "Undid" means a strictly later check on the same id read the
    record and confirmed the id. A later unreadable check is not a
    recant: it says nothing, and treating silence as a correction
    would hide exactly the failure being looked for.
    """
    rows = list(session.execute(
        select(LinkCheck.video_id, LinkCheck.checked_at, LinkCheck.evidence)
        .where(LinkCheck.platform == platform,
               LinkCheck.checked_at >= since,
               LinkCheck.video_id.isnot(None))
        .order_by(LinkCheck.checked_at)
    ))

    alive_after: dict[str, list[datetime]] = defaultdict(list)
    for video_id, when, evidence in rows:
        if evidence == ID_CONFIRMED:
            alive_after[video_id].append(when)

    days: dict[str, Day] = {}
    for video_id, when, evidence in rows:
        if evidence not in GONE_EVIDENCE:
            continue
        key = when.date().isoformat()
        day = days.setdefault(key, Day(day=key))
        day.said_gone += 1
        day.by_evidence[evidence] = day.by_evidence.get(evidence, 0) + 1
        if any(later > when for later in alive_after.get(video_id, ())):
            day.recanted += 1
            day.recanted_by_evidence[evidence] = (
                day.recanted_by_evidence.get(evidence, 0) + 1)
    return [days[key] for key in sorted(days)]


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin")
    parser.add_argument("--days", type=int, default=40)
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        table = recanted_by_day(
            session, args.platform,
            utc_now() - timedelta(days=args.days))

    if not table:
        print(f"no removals recorded for {args.platform} in "
              f"{args.days} days")
        return

    print(f"{args.platform}: removals recorded, and how many a later "
          f"check undid\n")
    print(f"{'day':12} {'gone':>6} {'undone':>7} {'share':>7}   "
          f"{'served-another':>15} {'page-said-gone':>15}")
    for day in table:
        served = day.by_evidence.get(SERVED_ANOTHER, 0)
        said = day.by_evidence.get(PAGE_SAYS_GONE, 0)
        served_undone = day.recanted_by_evidence.get(SERVED_ANOTHER, 0)
        said_undone = day.recanted_by_evidence.get(PAGE_SAYS_GONE, 0)
        bar = "#" * int(day.share * 40)
        print(f"{day.day:12} {day.said_gone:6} {day.recanted:7} "
              f"{day.share:6.0%}   {served_undone:>6}/{served:<8} "
              f"{said_undone:>6}/{said:<8} {bar}")
    print(
        "\nEach cell is undone/recorded. A removal 'undone' is one a\n"
        "later check read and confirmed alive -- which is either a\n"
        "reinstatement or the earlier check having been wrong, and\n"
        "from outside those look the same.\n\n"
        "What to look for: 'served another video' is inferred from a\n"
        "record belonging to a different post, which a page that\n"
        "failed to load its own content and fell through to a\n"
        "recommendation would also produce. 'page says the post is\n"
        "gone' is Douyin's own wording and is hard to produce by\n"
        "accident. If the first is undone far more often than the\n"
        "second, and only on the days the instrument was degraded,\n"
        "those removals are the instrument."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
