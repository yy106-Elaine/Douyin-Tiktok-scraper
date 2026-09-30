"""What the collection says so far, in the terms it can support.

    ./.venv/bin/python -m app.analyse
    ./.venv/bin/python -m app.analyse --csv findings.csv

Four tables and an export. The tables are the ones that can be read
off today's data without assuming anything it does not contain; the
export is for the survival analysis proper, which belongs in R or
lifelines and not here.

The arithmetic is deliberately plain. What is not plain, and what this
module mostly exists to enforce, is *which* comparisons the data
supports:

 -- A raw removal rate is not comparable across platforms. Douyin is
    searched by tag the day of posting; TikTok is searched by an
    English phrase and returns videos already weeks old, which is a
    survivor set: the ones pulled on day one never appear in it. So
    the cross-platform table reports collection age beside the rate,
    and the comparable number is the horizon below.

 -- A median time to removal needs half the population to have been
    removed. At a fifth, the median is not "long", it is undefined,
    and a number computed anyway is an artefact. So this reports
    survival at fixed horizons instead, and says how many events
    there are.

 -- A removal time is an interval, never an instant: gone by this
    check, alive at the last one. The width of that interval is the
    checking cadence, and it is printed beside every rate so nothing
    is ever quoted more precisely than the schedule allows.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import local, local_date
from .models import LinkCheck, SharedLink, WebVideo
from .survival import (
    Finding,
    age_at_collection,
    by_collection_age,
    findings,
    horizon,
    summarise,
)

#: The questions the horizon table asks. Short ones first: removals
#: cluster early, and a day is the resolution the daily pass supports.
HORIZONS: tuple[timedelta, ...] = (
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
)

PLATFORMS: tuple[str, ...] = ("douyin", "douyin_note", "tiktok", "youtube")


def own(session: Session, platform: str) -> list[Finding]:
    """This platform's findings, not its family's.

    `findings` groups 图文 under douyin, which is what the dashboard
    wants and the opposite of what a comparison between the two wants.
    """
    return [f for f in findings(session, platform) if f.platform == platform]


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _days(span: timedelta | None) -> str:
    if span is None:
        return "—"
    hours = span.total_seconds() / 3600
    return f"{hours / 24:.1f}d" if hours >= 24 else f"{hours:.0f}h"


def observed_days(session: Session, platform: str) -> dict[str, set[str]]:
    """Which videos this platform saw a check on, per local day.

    Built from the checks themselves rather than from a calendar, so a
    day the study did not run is an empty set and says so, instead of
    contributing a zero to a hazard series. 2026-09-27 is such a day.
    """
    seen: dict[str, set[str]] = {}
    for check in session.scalars(
        select(LinkCheck).where(
            LinkCheck.platform == platform, LinkCheck.target_kind == "video"
        )
    ):
        if check.video_id and check.checked_at:
            seen.setdefault(local_date(check.checked_at).isoformat(), set()).add(
                check.video_id
            )
    return seen


def daily_hazard(
    session: Session, platform: str, items: list[Finding]
) -> list[tuple[str, int, int, float | None]]:
    """(day, at risk, newly gone, hazard) for each day that was observed.

    At risk means: checked that day, and not already known to be gone
    before it. A day with no checks at all does not appear -- it is
    missing, not zero, and the difference is the whole reason the
    series is built from observations rather than from dates.
    """
    gone_on: dict[str, set[str]] = {}
    for finding in items:
        if finding.first_gone_ever:
            gone_on.setdefault(
                local_date(finding.first_gone_ever).isoformat(), set()
            ).add(finding.video_id)

    seen = observed_days(session, platform)
    out = []
    already: set[str] = set()
    for day in sorted(seen):
        checked = seen[day]
        at_risk = checked - already
        events = gone_on.get(day, set()) & checked
        rate = len(events) / len(at_risk) if at_risk else None
        out.append((day, len(at_risk), len(events), rate))
        already |= events
    return out


def captions(session: Session, platform: str) -> dict[str, str]:
    """The caption per video, for the export.

    Fetched pages first, because that is the caption as the platform
    served it. A link that was never fetched still gets a key, so the
    export can tell "no caption" from "not in this table" -- the 62
    captionless rows are a category, not a gap.
    """
    said: dict[str, str] = {}
    for row in session.scalars(
        select(WebVideo).where(WebVideo.platform == platform)
    ):
        if row.video_id:
            said[row.video_id] = (row.caption or "").replace("\n", " ")
    for link in session.scalars(
        select(SharedLink).where(SharedLink.platform == platform)
    ):
        if link.video_id:
            said.setdefault(link.video_id, "")
    return said


def export(session: Session, path: str) -> int:
    """One row per video, for a survival analysis done properly elsewhere.

    Times are the researcher's local wall clock, because that is what
    every other output here shows and a CSV that disagrees with the
    dashboard by four hours is a trap. The interval columns are what
    an interval-censored fit needs: last seen alive, first seen gone.
    """
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow([
            "platform", "video_id", "author_handle", "url",
            "published_at", "collected_at", "age_at_collection_hours",
            "first_checked_at", "last_alive_at", "first_gone_at",
            "came_back_at", "disappearances", "checks", "uninformative",
            "current", "outcome", "is_gone", "caption",
        ])
        for platform in PLATFORMS:
            said = captions(session, platform)
            for f in own(session, platform):
                age = age_at_collection(f)
                out.writerow([
                    f.platform, f.video_id, f.author_handle or "", f.url or "",
                    local(f.published_at) or "", local(f.collected_at) or "",
                    f"{age.total_seconds() / 3600:.1f}" if age else "",
                    local(f.first_checked_at) or "", local(f.last_alive_at) or "",
                    local(f.first_gone_ever) or "", local(f.came_back_at) or "",
                    f.disappearances, f.checks, f.uninformative,
                    f.current or "", f.outcome or "", int(bool(f.is_gone)),
                    said.get(f.video_id, "")[:500],
                ])
                written += 1
    return written


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", help="also write one row per video here")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        held = {p: own(session, p) for p in PLATFORMS}

        print("\n=== What was tracked, and what happened to it ===\n")
        print(f"{'platform':13} {'tracked':>8} {'gone':>6} {'alive':>6} "
              f"{'no info':>8} {'rate':>7} {'± window':>9}")
        for platform, items in held.items():
            s = summarise(items)
            print(f"{platform:13} {s.tracked:8} {s.gone:6} {s.alive:6} "
                  f"{s.unmeasured:8} {_pct(s.rate):>7} "
                  f"{_days(s.median_uncertainty):>9}")
        print("\n  rate = gone / (gone + alive). Videos never read are out of the\n"
              "  denominator, not assumed alive. ± window is the median width of\n"
              "  the removal intervals: no lifetime is known better than this.")

        print("\n=== How old each video was when we started watching ===\n")
        print("  A rate is only comparable within a band. A search that returns\n"
              "  month-old videos returns the ones that lasted a month.\n")
        for platform, items in held.items():
            bands = by_collection_age(items)
            if not bands:
                continue
            print(f"  {platform}")
            for label, s in bands:
                print(f"    {label:22} {s.tracked:5} tracked  "
                      f"{s.gone:4} gone  {_pct(s.rate):>7}")
            print()

        print("=== Removed within T of publication, among videos watched that early ===\n")
        print(f"{'platform':13} {'horizon':>8} {'eligible':>9} {'removed':>8} "
              f"{'survived':>9} {'too early':>10} {'rate':>7}")
        for platform, items in held.items():
            for age in HORIZONS:
                h = horizon(items, age)
                if not h.eligible:
                    continue
                print(f"{platform:13} {_days(age):>8} {h.eligible:9} {h.removed:8} "
                      f"{h.survived:9} {h.censored:10} {_pct(h.rate):>7}")
        print("\n  'eligible' excludes videos first seen after T -- nothing was\n"
              "  watching them that early, so for them the question has no answer.\n"
              "  'too early' is still alive but not yet old enough to say.\n"
              "  This is the number that compares across platforms; the raw rate\n"
              "  above is not.")

        print("\n=== New removals per day observed ===\n")
        for platform, items in held.items():
            rows = daily_hazard(session, platform, items)
            if not rows:
                continue
            print(f"  {platform}")
            for day, at_risk, events, rate in rows:
                bar = "#" * min(events, 40)
                print(f"    {day}  at risk {at_risk:4}  gone {events:3}  "
                      f"{_pct(rate):>6}  {bar}")
            print()
        print("  Days the study did not run are absent, never zero. A hazard of\n"
              "  zero means it looked and found nothing; a missing day means it\n"
              "  did not look, and the removals of that day are dated to the next\n"
              "  one it did.")

        back = [
            (p, f) for p, items in held.items() for f in items if f.came_back_at
        ]
        if back:
            print("\n=== Came back ===\n")
            for platform, f in sorted(back, key=lambda pair: pair[1].came_back_at):
                print(f"  {platform:12} {f.video_id}")
                print(f"     gone by {local(f.first_gone_ever)}  "
                      f"back by {local(f.came_back_at)}")
            print("\n  Those are the times the instrument looked, not the times\n"
                  "  anything happened. The data supports an interval, never a\n"
                  "  duration. With this many events it is a description, not a\n"
                  "  rate.")

        if args.csv:
            written = export(session, args.csv)
            print(f"\n{written} row(s) written to {args.csv}")


if __name__ == "__main__":  # pragma: no cover
    main()
