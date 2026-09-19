"""Remove capture rows a parser bug made untrustworthy.

The Douyin post boundary matched nothing until 2026-09-19, so every
frame was segmented as a single post and each stored row was assembled
from the first matching node of each kind anywhere on screen. With two
or three videos in the tree at once, that pairs one video's author with
another's caption. The rows cannot be repaired: the payload records what
the parser produced, and the association it got wrong was never
observed correctly in the first place.

Two things this deliberately does not delete.

**The links.** A shared link carries its own video id, resolved by
following a redirect, and none of that went through the parser. Those
rows are sound. What is removed is their pairing to a capture, because
the capture is what was wrong -- the link then stands on its own, with
an id and a publication time and no claim about a caption it cannot
support.

**Anything after the cutoff.** The default is the first collection run
with the fix in place, and `--before` is required to be explicit rather
than inferred, so re-running this cannot quietly widen.

Dry by default. `--delete` is the only thing that writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .models import CaptureEvent, SharedLink
from .parsers import PLATFORM_TABLES

#: The first Douyin run collected with a working post boundary.
DEFAULT_CUTOFF = "2026-09-19T02:40:00"


def survey(session: Session, platform: str, before: datetime) -> dict[str, int]:
    model, _ = PLATFORM_TABLES[platform]
    posts = session.scalars(select(model).where(model.captured_at < before)).all()
    event_ids = {post.capture_event_id for post in posts}
    links = (
        session.scalars(
            select(func.count())
            .select_from(SharedLink)
            .where(SharedLink.matched_capture_id.in_(event_ids))
        ).one()
        if event_ids
        else 0
    )
    return {"posts": len(posts), "capture events": len(event_ids), "links unpaired": links}


def purge(session: Session, platform: str, before: datetime) -> dict[str, int]:
    model, _ = PLATFORM_TABLES[platform]
    counts = survey(session, platform, before)

    event_ids = {
        post.capture_event_id
        for post in session.scalars(select(model).where(model.captured_at < before))
    }
    if event_ids:
        # The link keeps its id and its time; only the claim that it
        # belongs to a particular capture goes.
        session.execute(
            update(SharedLink)
            .where(SharedLink.matched_capture_id.in_(event_ids))
            .values(matched_capture_id=None, pairing_method=None)
        )
    session.execute(delete(model).where(model.captured_at < before))
    if event_ids:
        session.execute(delete(CaptureEvent).where(CaptureEvent.id.in_(event_ids)))
    session.commit()
    return counts


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin")
    parser.add_argument("--before", default=DEFAULT_CUTOFF)
    parser.add_argument(
        "--delete", action="store_true", help="actually remove them; otherwise print"
    )
    args = parser.parse_args()

    before = datetime.fromisoformat(args.before)
    from .db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        counts = purge(session, args.platform, before) if args.delete else survey(
            session, args.platform, before
        )

    verb = "removed" if args.delete else "would remove"
    print(f"{verb}, for {args.platform} captured before {before}:")
    for label, count in counts.items():
        print(f"  {count:>5}  {label}")
    if not args.delete:
        print("\nNothing was changed. Add --delete to apply.")
    else:
        print("\nRe-run: python -m app.relevance && python -m app.resolve")


if __name__ == "__main__":  # pragma: no cover
    main()
