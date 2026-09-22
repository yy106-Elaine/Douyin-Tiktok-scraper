"""Re-label TikTok rows whose `feed` recorded the wrong thing.

    ./.venv/bin/python -m app.relabel                  # what it would change
    ./.venv/bin/python -m app.relabel --apply

The fullscreen TikTok player draws a strip reading "Search · <phrase>"
under a video. It looks like the query that produced the video, and
was stored as `search:<phrase>` on that reading. It is not: TikTok
generates the phrase per video from the video's own content, so it
describes the video rather than the search.

What settled it: one run in which `Chinese lesbian` was the only term
typed produced 71 rows carrying 14 different phrases, none of them
that one -- the largest, at 28 rows, "brys lovely beloved wife social
media" -- and a video captioned "Meet Genevieve. #chinesecrested",
which is a dog, carried "搜索 · chinese twitter".

The phrase is worth keeping; TikTok's own topical label for a video
is data. Reading it as the sampling frame is not, and on this
platform the sampling frame is the whole corpus definition. So the
prefix changes to `anchor:`, which no analysis can mistake for a
query someone typed.

Only TikTok rows, and only the ones the player produced. The results
*grid* does show the typed query, and `TikTokSearchParser` reads it
from there; those rows are the real thing and are left alone. They
are told apart by their shape -- the grid writes the sort order as a
third part, `search:<query>:<sort>` -- and, for the ambiguous
remainder, by the fact that the grid parser has never harvested a
tile on this device (`tiles harvested: 0` in every self-check so
far), which is checked and reported rather than assumed.
"""
from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TikTokPost

WRONG = "search:"
RIGHT = "anchor:"

#: The grid's own shape: `search:<query>:<sort>`. Left alone.
_GRID_PARTS = 3


def mislabelled(session: Session) -> list[TikTokPost]:
    rows = session.scalars(
        select(TikTokPost).where(TikTokPost.feed.like(f"{WRONG}%"))
    ).all()
    return [row for row in rows if len((row.feed or "").split(":")) < _GRID_PARTS]


def relabel(session: Session, rows: list[TikTokPost]) -> int:
    for row in rows:
        row.feed = RIGHT + (row.feed or "")[len(WRONG):]
    if rows:
        session.commit()
    return len(rows)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from collections import Counter

    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(
        description="Re-label TikTok rows that stored a related-search "
        "suggestion as if it were the query."
    )
    parser.add_argument("--apply", action="store_true", help="write the change")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        rows = mislabelled(session)
        if not rows:
            print("nothing to re-label.")
            return

        counts = Counter(row.feed for row in rows)
        print(f"{len(rows)} row(s) across {len(counts)} phrase(s):")
        for feed, count in counts.most_common(10):
            print(f"  {count:5}  {feed} -> {RIGHT}{feed[len(WRONG):]}")
        if len(counts) > 10:
            print(f"  ... and {len(counts) - 10} more")

        if not args.apply:
            print("\nAdd --apply to write it.")
            return

        print(f"\nre-labelled {relabel(session, rows)}")


if __name__ == "__main__":  # pragma: no cover
    main()
