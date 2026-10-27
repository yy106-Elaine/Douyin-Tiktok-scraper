"""Status at the end of observation, by when each post entered the study.

    ./.venv/bin/python -m app.cohorts
    ./.venv/bin/python -m app.cohorts --platform douyin_note --by week

This is the analysis the whole corpus can carry, including the weeks
the instrument was faulty.

Three faults are on the record and all three damage *timing*: the
image blocking of 10-06 to 10-14 made removals look later than they
were, the two-browser pass of 10-09 to 10-13 invented removals on
video, and `filter_detail` went unread until 10-14 so some removals
were filed as "we learned nothing". Everything computed from the date
a removal was *first detected* -- hazards, lifetimes, the T-horizon
table -- is only sound from 10-15.

None of that touches the question asked here, which is:

    of the posts collected in week W, what share is still publicly
    visible at the last time we looked?

That needs the collection date and the latest check, and the latest
check is made by the current instrument. A post the two-browser pass
wrongly called gone was read alive again afterwards, so the final
state corrects it. A removal the blocking made us miss on 10-08 is
still visible as a removal today. The faulty weeks cost precision
about *when*, and nothing about *whether*.

One thing the final state cannot repair: a post whose latest check
read nothing. Those are counted and reported, never folded into
either side -- a post we could not reach is not evidence that it
survived.

Posts collected later have been watched for less time, so the cohorts
are not comparable to each other as rates. The exposure column says
how long each was watched; read down it before reading across.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .survival import Finding, Summary, findings, summarise


def cohort_of(finding: Finding, by: str) -> str | None:
    """Which collection cohort this post belongs to."""
    when = finding.collected_at
    if when is None:
        return None
    if by == "day":
        return when.strftime("%Y-%m-%d")
    # ISO week, labelled by its Monday, which reads as a date rather
    # than as a week number nobody can place in October.
    monday = when - timedelta(days=when.weekday())
    return monday.strftime("%Y-%m-%d")


def exposure(items: list[Finding]) -> timedelta | None:
    """Median time from collection to the last look.

    Median rather than mean: one post collected on the first day and
    checked ever since would otherwise make a week of fresh posts
    look long-watched.
    """
    spans = [
        finding.last_checked_at - finding.collected_at
        for finding in items
        if finding.last_checked_at and finding.collected_at
    ]
    if not spans:
        return None
    spans.sort()
    middle = len(spans) // 2
    if len(spans) % 2:
        return spans[middle]
    return (spans[middle - 1] + spans[middle]) / 2


def cohorts(session: Session, platform: str | None = None,
            by: str = "week") -> list[tuple[str, Summary, timedelta | None]]:
    """(cohort, summary, median exposure), oldest first."""
    grouped: dict[str, list[Finding]] = {}
    for finding in findings(session, platform):
        label = cohort_of(finding, by)
        if label is None:
            continue
        grouped.setdefault(label, []).append(finding)
    return [
        (label, summarise(grouped[label]), exposure(grouped[label]))
        for label in sorted(grouped)
    ]


def _days(span: timedelta | None) -> str:
    return "—" if span is None else f"{span.total_seconds() / 86400:.1f}d"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def report(session: Session, platform: str | None = None,
           by: str = "week") -> str:
    rows = cohorts(session, platform, by)
    if not rows:
        return "nothing collected with a date on it.\n"

    out = [
        "=== Still visible at the last look, by when it was collected ===",
        "",
        f"  {'collected':<12} {'posts':>6} {'gone':>6} {'alive':>6} "
        f"{'unknown':>8} {'gone rate':>10} {'watched':>9}",
    ]
    for label, summary, span in rows:
        out.append(
            f"  {label:<12} {summary.tracked:6} {summary.gone:6} "
            f"{summary.alive:6} {summary.unmeasured:8} "
            f"{_pct(summary.rate):>10} {_days(span):>9}"
        )
    out += [
        "",
        "  'unknown' is a post whose latest check read nothing. It is",
        "  out of the rate's denominator, not counted as surviving.",
        "",
        "  'watched' is the median time from collection to the last",
        "  look. Cohorts with different exposure are not comparable as",
        "  rates -- a week watched for five days and a week watched for",
        "  five weeks answer different questions.",
        "",
        "  The instrument faults of 10-06 to 10-14 moved removal *dates*",
        "  and are not in this table: it asks only what the current,",
        "  repaired instrument sees now. Timing figures belong to the",
        "  10-15 onwards window instead.",
        "",
    ]
    return "\n".join(out)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default=None,
                        help="one platform; omit for each in turn")
    parser.add_argument("--by", default="week", choices=("week", "day"))
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        if args.platform:
            print(f"\n--- {args.platform}")
            print(report(session, args.platform, args.by))
            return
        from .platforms import PLATFORMS

        for platform in PLATFORMS:
            rows = cohorts(session, platform, args.by)
            if not rows:
                continue
            print(f"\n--- {platform}")
            print(report(session, platform, args.by))


if __name__ == "__main__":  # pragma: no cover
    main()
