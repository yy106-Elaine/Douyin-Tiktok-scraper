"""Delete the rows the topic filter excluded, after writing them down.

A YouTube search for the keywords returns mostly other things: 1,072
of 1,126 rows over three days were adult nappies, a children's
cartoon, Japanese vlogs, product listings. That ratio is a finding --
the community's practice on YouTube is thin, and the search reaches it
through a great deal of noise -- but the rows themselves are not the
corpus and do not belong in the table or the survival analysis.

**The count is the finding; the rows are not.** So this writes them to
a CSV before removing them, with the reason each was excluded. The
classifier is fallible -- 拉拉裤 and 巴拉拉小魔仙 both had to be taught
-- and "read a category before trusting it" stops being possible the
moment the rows are gone. The CSV is what keeps it possible.

What goes: the post row, the `capture_events` payload it came from,
and any re-checks already made against its id. Nothing that is in
scope is touched, and nothing on a platform with no topic filter --
Douyin and TikTok are sampled from community hashtags, where the
search is the filter.

Dry by default. `--apply` is the only thing that writes.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CaptureEvent, LinkCheck
from .parsers import PLATFORM_TABLES
from .platforms import filter_policy
from .relevance import HIDDEN
from .views import in_scope_filter

#: Columns written to the audit CSV.
_FIELDS = (
    "video_id",
    "posted_on",
    "author_handle",
    "author_name",
    "caption",
    "relevance",
    "video_url",
    "captured_at",
)


def excluded(session: Session, platform: str) -> list:
    """Rows the topic filter put out of scope, on a filtered platform."""
    if filter_policy(platform) == "none":
        return []
    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return []
    model, _ = registered
    return list(
        session.scalars(
            select(model)
            .where(model.relevance.in_(HIDDEN), ~in_scope_filter(model, platform))
            .order_by(model.captured_at)
        )
    )


def reasons(rows) -> Counter:
    return Counter(row.relevance for row in rows)


def write_audit(rows, path: Path) -> int:
    """Record what is about to go, so the filter stays reviewable."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field, None) for field in _FIELDS})
    return len(rows)


def prune(session: Session, platform: str, apply: bool = False) -> dict[str, int]:
    rows = excluded(session, platform)
    report = {"rows": len(rows), "checks": 0, "events": 0}
    if not apply or not rows:
        return report

    for row in rows:
        if row.video_id:
            for check in session.scalars(
                select(LinkCheck).where(
                    LinkCheck.platform == platform, LinkCheck.video_id == row.video_id
                )
            ):
                session.delete(check)
                report["checks"] += 1
        event = session.get(CaptureEvent, row.capture_event_id)
        session.delete(row)
        if event is not None:
            session.delete(event)
            report["events"] += 1

    session.commit()
    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="youtube")
    parser.add_argument(
        "--audit",
        default="",
        help="where to write the CSV (default: excluded-<platform>-<today>.csv)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write; otherwise report and stop"
    )
    args = parser.parse_args()

    path = Path(
        args.audit or f"excluded-{args.platform}-{date.today().isoformat()}.csv"
    )

    init_db()
    with SessionLocal() as session:
        rows = excluded(session, args.platform)
        for reason, count in reasons(rows).most_common():
            print(f"{count:6,}  {reason}")
        print(f"{len(rows):6,}  total")

        if not args.apply:
            print("\ndry run -- nothing removed. Add --apply to remove them.")
            return

        write_audit(rows, path)
        print(f"\nwrote {path}")
        report = prune(session, args.platform, apply=True)
        print(
            f"removed {report['rows']:,} row(s), "
            f"{report['events']:,} capture event(s), "
            f"{report['checks']:,} re-check(s)"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
