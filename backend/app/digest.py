"""The numbers a chapter needs, on one screen, each with its caveat.

    ./.venv/bin/python -m app.digest

`app.analyse` prints everything the collection can say, which is the
right thing for checking the instrument and the wrong thing for
writing: a figure that arrives in a page of other figures gets quoted
without the sentence that bounds it. This prints the handful that a
6,000-word chapter has room for, and prints the bound beside each
one rather than in a methods file the reader of the number will not
open.

Nothing here is computed differently from `app.analyse` or
`app.cohorts`. It is a selection, and the selection is the point.
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LinkCheck
from .survival import findings, removal_ages, summarise

#: The platform the chapter rests on. Video is excluded from every
#: headline figure -- 304 posts, a third of them last read days
#: before the end, and cohort rates between 14% and 58%.
MAIN = "douyin_note"


def _days(span: timedelta) -> float:
    return span.total_seconds() / 86400


def _quartiles(spans: list[timedelta]) -> tuple[float, float, float]:
    """Median and the middle half, in days."""
    days = sorted(_days(s) for s in spans)
    if not days:
        return (0.0, 0.0, 0.0)

    def at(share: float) -> float:
        index = min(int(share * len(days)), len(days) - 1)
        return days[index]

    return at(0.25), at(0.5), at(0.75)


def reasons_by_post(session: Session, platform: str) -> list[tuple[str, int]]:
    """One row per post, on its latest check that named a reason.

    Per post, not per check. The per-check count is the one the
    collection makes naturally and it is the wrong unit for a claim
    about posts: a post checked daily for five weeks contributes
    thirty-five rows and one post.
    """
    latest: dict[str, tuple] = {}
    rows = session.execute(
        select(LinkCheck.video_id, LinkCheck.checked_at,
               LinkCheck.filter_reason)
        .where(LinkCheck.platform == platform,
               LinkCheck.filter_reason.isnot(None))
    )
    for video_id, checked_at, reason in rows:
        seen = latest.get(video_id)
        if seen is None or checked_at >= seen[0]:
            latest[video_id] = (checked_at, reason)
    counts: dict[str, int] = {}
    for _, (_, reason) in latest.items():
        counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda pair: -pair[1])


#: The reasons in which the platform names its own review. Everything
#: else is a visibility state that an author could also have set.
NAMES_A_REVIEW = frozenset({"status_audit_not_pass", "status_audit_self_see"})


def report(session: Session, platform: str = MAIN) -> str:
    items = findings(session, platform)
    summary = summarise(items)
    ages = removal_ages(items)
    low, mid, high = _quartiles(ages)
    reasons = reasons_by_post(session, platform)
    with_reason = sum(count for _, count in reasons)
    reviewed = sum(count for reason, count in reasons
                   if reason in NAMES_A_REVIEW)

    out = [
        "=== Figures for the chapter ===",
        f"    platform: {platform}",
        "",
        "-- how much",
        f"   {summary.gone:,} of {summary.gone + summary.alive:,} posts no "
        f"longer publicly visible ({(summary.rate or 0) * 100:.1f}%)",
        "   Say: no longer visible to an ordinary viewer. Not 'removed by",
        "   the platform' -- see 'who did it' below.",
        "",
        "-- how fast, among the posts that went",
        f"   median {mid:.1f}d, middle half {low:.1f}d-{high:.1f}d "
        f"(n = {len(ages):,})",
        "   Say: of the posts that disappeared, half were gone within",
        f"   {mid:.1f} days. NOT 'a post lasts {mid:.1f} days' -- the posts that",
        "   will go slowly have not gone yet, so this drifts upward the",
        "   longer the study runs.",
        "",
        "-- who did it, per post, on the latest check that named a reason",
    ]
    for reason, count in reasons:
        share = 100 * count / with_reason if with_reason else 0
        mark = "  <- platform names a review" if reason in NAMES_A_REVIEW else ""
        out.append(f"   {reason:<24} {count:5,}  {share:5.1f}%{mark}")
    out += [
        "",
        f"   {reviewed} of {with_reason:,} posts carry a word that names a",
        "   review. That is the LOWER BOUND on moderation, not a measure",
        "   of it: an audit result can arrive as a visibility change, and",
        "   then it is indistinguishable from an author's own setting.",
        "",
        "-- what cannot be said",
        "   'the platform removed X%'  -- the field records a state, not an",
        "                                 actor",
        "   'authors removed X%'       -- same field, same problem",
        "   'TikTok removes nothing'   -- nil result, unverified mechanism",
        "   a video-only rate          -- 304 posts, a third read days late",
        "",
    ]
    return "\n".join(out)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default=MAIN)
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        print(report(session, args.platform))


if __name__ == "__main__":  # pragma: no cover
    main()
