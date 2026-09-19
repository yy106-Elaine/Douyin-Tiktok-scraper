"""Fold a post's blank first read into the row that has its caption.

    19:50  '珩舟'  likes=8  caption=None
    19:50  '珩舟'  likes=8  caption='#短发 #lwl'

One video, two rows, one minute apart. A post's identity on the device
is its author plus the head of its caption, so a read taken before the
caption drew has a different identity from the read taken after -- and
the assisted loop guarantees a gap between the two, because the share
sheet covers the feed for several seconds in between.

The blank row holds nothing the other does not. It is not evidence of
a second video; it is the same video, read early. Left alone it
inflates the row count, halves every caption-coverage figure, and puts
two lines in the dashboard for one post.

What is deleted is the derived row. The `capture_events` payload it was
built from stays, so the observation as the device reported it is still
on file and the deletion is reversible by re-deriving.

Dry by default. `--apply` is the only thing that writes.
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import SharedLink
from .parsers import PLATFORM_TABLES

#: Fields a blank row may still contribute to the row that absorbs it.
#: Not the caption, which is what makes the other row the keeper.
_CARRIED = (
    "author_handle",
    "author_name",
    "posted_at_raw",
    "posted_on",
    "music",
    "feed",
    "like_count",
    "comment_count",
    "share_count",
    "save_count",
    "is_ad",
    "is_ai_generated",
)


def _author_of(post) -> str | None:
    name = (post.author_name or post.author_handle or "").strip()
    return name or None


def _is_blank(post) -> bool:
    """A read with no caption and no id: nothing to tell it apart by."""
    return not (post.caption or "").strip() and not post.video_id


def pairs(session: Session, platform: str) -> list[tuple[object, object]]:
    """Blank rows and the captioned row each one belongs to.

    Grouped by participant, day and author, because that is as far as
    the device's own identity goes. Within a group, a blank row is
    matched to a captioned row by like count -- the number that is on
    screen before the caption is and does not change while it is
    watched. A blank row with no counts is matched only when the author
    posted exactly one captioned video that day, so there is nothing to
    be wrong about.

    Anything ambiguous is left alone and reported, because two rows
    merged in error lose a video, which is worse than a duplicate.
    """
    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return []
    model, _ = registered

    groups: dict[tuple, list] = defaultdict(list)
    for post in session.scalars(select(model)):
        author = _author_of(post)
        if author is None:
            continue
        key = (post.participant_id, post.captured_at.date(), author)
        groups[key].append(post)

    matched: list[tuple[object, object]] = []
    for members in groups.values():
        blanks = [post for post in members if _is_blank(post)]
        captioned = [post for post in members if not _is_blank(post)]
        if not blanks or not captioned:
            continue

        for blank in blanks:
            if blank.like_count is not None:
                candidates = [
                    post for post in captioned if post.like_count == blank.like_count
                ]
            else:
                candidates = captioned
            if len(candidates) == 1:
                matched.append((blank, candidates[0]))
    return matched


def absorb(session: Session, platform: str, apply: bool = False) -> dict[str, int]:
    """Merge each blank row into its captioned one. Returns a report."""
    found = pairs(session, platform)
    report = {"blank_rows_folded": len(found), "fields_carried": 0}
    if not apply or not found:
        return report

    for blank, keeper in found:
        for field in _CARRIED:
            if getattr(keeper, field, None) in (None, ""):
                value = getattr(blank, field, None)
                if value not in (None, ""):
                    setattr(keeper, field, value)
                    report["fields_carried"] += 1
        # The verbatim payload stays; only the derived row goes. A link
        # cannot be paired to a blank row -- pairing sets a video id --
        # but clear it rather than depend on that staying true.
        session.execute(
            update(SharedLink)
            .where(SharedLink.matched_capture_id == blank.capture_event_id)
            .values(matched_capture_id=None, pairing_method=None)
        )
        session.delete(blank)

    session.commit()
    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin")
    parser.add_argument(
        "--apply", action="store_true", help="write; otherwise report and stop"
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        if not args.apply:
            for blank, keeper in pairs(session, args.platform):
                print(
                    f"{_author_of(blank)}  likes={blank.like_count}  "
                    f"-> {(keeper.caption or '')[:50]!r}"
                )
        report = absorb(session, args.platform, apply=args.apply)
        verb = "folded" if args.apply else "would fold"
        print(f"{verb} {report['blank_rows_folded']} blank row(s)")
        if args.apply:
            print(f"carried {report['fields_carried']} field(s) across")


if __name__ == "__main__":  # pragma: no cover
    main()
