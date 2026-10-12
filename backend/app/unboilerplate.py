"""Clear the site's own sentence out of captions it was stored as.

    ./.venv/bin/python -m app.unboilerplate          # count them
    ./.venv/bin/python -m app.unboilerplate --apply  # clear them

A Douyin page that does not hand over its record still carries a
description, and twice now that description has been the platform's
rather than the author's. The surface parser is guarded against both
shapes, but the second shape was only recognised after it had
already been written to `web_videos` as the caption of several
hundred posts.

A wrong caption is worse than none, three times over. The topic
filter reads it, finds no community tag in a sentence the platform
wrote, and declines to keep the post's pictures -- and for a post
later removed that was the archive's only chance. The caption is
what the content coding will read. And a caption is quoted in a
thesis as the author's words.

So they are set back to NULL, which is what the passes already treat
as "cannot tell": a post with no caption is kept, not filtered out.
The rows stay, their `parsed_by` stays `surface`, and
`app.daily --unarchived` will read them again properly.
"""
from __future__ import annotations

import argparse

from sqlalchemy import or_, select

from .douyin_page import _BOILERPLATE
from .models import WebVideo


def boilerplate_rows(session) -> list[WebVideo]:
    """Rows whose stored caption is the site's wording, not a person's."""
    found = []
    for row in session.scalars(
        select(WebVideo).where(WebVideo.caption.isnot(None))
    ):
        if _BOILERPLATE.search(row.caption or ""):
            found.append(row)
    return found


def clear(rows: list[WebVideo]) -> int:
    """Set each caption to NULL. Returns how many were changed."""
    for row in rows:
        row.caption = None
    return len(rows)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="clear them; otherwise count and stop")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        rows = boilerplate_rows(session)
        by_platform: dict[str, int] = {}
        for row in rows:
            by_platform[row.platform] = by_platform.get(row.platform, 0) + 1

        print(f"{len(rows)} row(s) whose caption is the site's own wording")
        for name, count in sorted(by_platform.items()):
            print(f"  {name:14} {count}")
        for row in rows[:3]:
            print(f"  e.g. {row.video_id}: {(row.caption or '')[:46]}")

        if not rows:
            return
        if not args.apply:
            print("\nAdd --apply to clear them. They become captionless, "
                  "which the passes treat as 'cannot tell' and so keep.")
            return

        changed = clear(rows)
        session.commit()
        print(f"\ncleared {changed}; re-read them with\n"
              "    python -m app.daily --platform douyin_note --unarchived --apply")


if __name__ == "__main__":  # pragma: no cover
    main()
