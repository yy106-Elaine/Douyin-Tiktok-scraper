"""Share texts pasted in by hand, when the phone cannot reach the backend.

    ./.venv/bin/python -m app.paste --file today.txt
    pbpaste | ./.venv/bin/python -m app.paste

The phone uploads over the local network, and on a hotel network, a
hotspot that hands out no IPv4, or any network with client isolation,
it cannot. The collection does not have to stop for that: Douyin's own
share sheet produces a blob that already carries the id, the author and
the caption, and this reads that blob.

    5.61 复制打开抖音，看看【酸奶烧烧的作品】拉拉们都是怎么谈上的啊
    #拉子们 #lwl #le https://www.iesdouyin.com/share/note/7689.../ :8p

One blob per paragraph; blank lines separate them, so a whole session's
worth can be pasted at once. Everything downstream is unchanged: these
become the same `SharedLink` rows the phone would have produced, and
`app.resolve`, `app.daily` and the filter treat them identically.

What it does not do is invent a capture. A pasted link has no screen
observation behind it, so `source` marks it `pasted` and analysis that
depends on the passive stream can exclude it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as utc_now
from .links import describe, extract
from .models import SharedLink

#: Blank-line separated. A share blob is a paragraph and never
#: contains a blank line, so this splits exactly where a person's
#: pasting does.
def blocks(text: str) -> list[str]:
    """The blobs in this text, each one once.

    A paste that landed twice -- the ordinary terminal accident, and
    one that has happened -- would otherwise be reported as twice as
    many posts as were collected, and the dry run's count is the only
    check a person has before storing them. Identity is the link:
    two blobs pointing at the same URL are one sighting, however
    their surrounding junk differs.
    """
    out: list[str] = []
    seen: set[str] = set()
    for chunk in (text or "").replace("\r\n", "\n").split("\n\n"):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        link = extract(cleaned)
        key = link.video_id or link.raw_url or cleaned
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def store(
    session: Session,
    text: str,
    participant_id: str,
    shared_at: datetime | None = None,
) -> tuple[SharedLink | None, str]:
    """One blob in, one row (or a reason there is none).

    Already-known links are skipped rather than duplicated: pasting
    the same session twice is the ordinary accident here, and a second
    row would be a second sighting that never happened.

    **Both forms of "already known" are checked.** Matching on the
    video id alone left the guard switched off for exactly the links
    that need it: a Douyin share blob carries a `v.douyin.com` short
    link and no id until `app.resolve` has followed it, so a batch
    pasted twice produced two rows for every post in it. The short
    link is the identity until the id exists, so it is matched too.
    """
    link = extract(text)
    if not link.video_id and not link.raw_url:
        return None, "no link in this text"

    if link.video_id:
        seen = session.scalar(
            select(SharedLink).where(SharedLink.video_id == link.video_id)
        )
        if seen is not None:
            return None, f"{link.video_id} already known"
    elif link.raw_url:
        seen = session.scalar(
            select(SharedLink).where(SharedLink.raw_text.contains(link.raw_url))
        )
        if seen is not None:
            return None, f"{link.raw_url} already known"

    said = describe(text)
    row = SharedLink(
        participant_id=participant_id,
        platform=link.platform or "douyin",
        raw_text=text,
        video_id=link.video_id,
        author_handle=link.author_handle,
        canonical_url=link.canonical_url,
        shared_at=shared_at or utc_now(),
        source="pasted",
    )
    session.add(row)
    session.commit()

    what = link.video_id or "short link, needs app.resolve"
    who = f" | {said.author_name}" if said.author_name else ""
    return row, f"{link.platform or 'douyin'}  {what}{who}"


def _when(said: str) -> datetime:
    """A date or a date and time, in the researcher's zone, as UTC.

    Stored columns are UTC and the person types wall clock, so the
    conversion belongs here rather than in anyone's head. A bare date
    means midday, not midnight: the true time is somewhere in that day
    and the middle is the reading that is least wrong.
    """
    from zoneinfo import ZoneInfo

    from .clock import zone

    text = said.strip()
    for shape, midday in (
        ("%Y-%m-%d %H:%M", False),
        ("%Y-%m-%dT%H:%M", False),
        ("%Y-%m-%d", True),
    ):
        try:
            when = datetime.strptime(text, shape)
        except ValueError:
            continue
        if midday:
            when = when.replace(hour=12)
        local: ZoneInfo = zone()
        return (
            when.replace(tzinfo=local)
            .astimezone(__import__("datetime").timezone.utc)
            .replace(tzinfo=None)
        )
    raise SystemExit(f"cannot read a time from {said!r}: use 2026-09-27 or 2026-09-27 22:10")


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", help="a file of share texts, blank line between each"
    )
    parser.add_argument(
        "--participant", default="P001", help="whose collection this is"
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually write the rows"
    )
    parser.add_argument(
        "--collected",
        metavar="WHEN",
        help=(
            "when these were actually found on the phone, in local time: "
            "2026-09-27 or 2026-09-27 22:10. Defaults to now, which is "
            "right only if the pasting follows the searching. A batch "
            "carried for a day is a sighting a day old, and the age of a "
            "post at collection is one of the things this measures"
        ),
    )
    args = parser.parse_args()

    collected = _when(args.collected) if args.collected else None

    text = (
        open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    )
    chunks = blocks(text)
    if not chunks:
        print("nothing pasted.")
        return

    if not args.apply:
        print(f"{len(chunks)} block(s). What they say:\n")
        for index, chunk in enumerate(chunks, start=1):
            link = extract(chunk)
            said = describe(chunk)
            print(
                f"[{index}] {link.platform or '?':12} "
                f"{link.video_id or '(short link)'}"
                f"{'  | ' + said.author_name if said.author_name else ''}"
            )
            if said.caption:
                print(f"     {said.caption[:70]}")
        print("\nAdd --apply to store them.")
        return

    init_db()
    stored = skipped = 0
    with SessionLocal() as session:
        for index, chunk in enumerate(chunks, start=1):
            row, why = store(
                session, chunk, args.participant, shared_at=collected
            )
            print(f"[{index}] {why}")
            if row is None:
                skipped += 1
            else:
                stored += 1

    print(f"\nstored {stored}; skipped {skipped}")
    if stored:
        print(
            "next:\n"
            "  ./.venv/bin/python -m app.resolve   # only if any were short links\n"
            "  ./.venv/bin/python -m app.daily --platform douyin_note "
            "--new-only --apply"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
