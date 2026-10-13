"""The ids whose last check today read nothing, one per line.

    ./.venv/bin/python -m app.unreadable --platform douyin_note > /tmp/blank.txt
    ./.venv/bin/python -m app.daily --platform douyin_note --apply \
        --only-from /tmp/blank.txt --forget-by tab

Written for one job: comparing two ways of forgetting on the *same*
pages. Three arms have now been measured -- `blank` at 20/39/79%,
`storage` at 35%, `tab` at 1/18 and 1/8 -- and every one of them read
a different set of posts, because each run takes whatever was due.
So the comparison has a second variable in it, and the honest reading
of "tab is better" is "tab, on 26 pages, on a different day, on
different posts".

If unreadability belongs to the *post* -- a note whose author is
gone, a kind of post the watched endpoints never carry -- then the
arms are the same and the small clean sample was a lucky draw. Handing
the failures straight back to another arm is what tells the two
apart, and nothing else here can.

Prints ids and nothing else, so it pipes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as utc_now
from .models import LinkCheck

#: What a page that answered but said nothing is filed as. Never
#: GONE: a page that could not be read is not evidence of a removal,
#: and conflating the two would turn a bad afternoon of scraping into
#: a spike in the study's own finding.
NOTHING_READ = "NOTHING_READ"


def unreadable_since(session: Session, platform: str,
                     since: datetime) -> list[str]:
    """Ids whose most recent check at or after `since` read nothing.

    Most recent, not any: a post that was unreadable at ten and read
    at noon is a post that was read. Asking for "any unreadable check
    today" would hand back pages that are already answered and make
    the retry look worse than it is.
    """
    latest: dict[str, tuple[datetime, str | None]] = {}
    rows = session.execute(
        select(LinkCheck.video_id, LinkCheck.checked_at, LinkCheck.evidence)
        .where(LinkCheck.platform == platform,
               LinkCheck.checked_at >= since,
               LinkCheck.video_id.isnot(None))
    )
    for video_id, checked_at, evidence in rows:
        seen = latest.get(video_id)
        if seen is None or checked_at >= seen[0]:
            latest[video_id] = (checked_at, evidence)
    return sorted(
        video_id for video_id, (_, evidence) in latest.items()
        if evidence == NOTHING_READ
    )


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin_note")
    parser.add_argument("--hours", type=float, default=12.0,
                        help="how far back to look (default 12)")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        for video_id in unreadable_since(
                session, args.platform,
                utc_now() - timedelta(hours=args.hours)):
            print(video_id)


if __name__ == "__main__":  # pragma: no cover
    main()
