"""Everything this study holds about one account, by its 抖音号.

    ./.venv/bin/python -m app.account 981373074
    ./.venv/bin/python -m app.account 66317444335 --checks

Written after the first two interviews. One interviewee said nothing
of hers had ever been removed; the corpus says otherwise. Another
said that *everything* about couples gets throttled. Both claims are
about particular videos, and neither can be weighed without putting
the account's own record on one screen: what was posted, what the
check saw on each day, and where the downloaded file is so the video
can actually be watched.

Two readings this is built to tell apart:

**Gone and stayed gone.** The page says the post is not there, or
the API filters it out, and later checks agree. That is a removal.

**Gone and back.** A link that failed on one day and worked on
another. This study has recorded a lot of those, and at least two
sources for them: Douyin putting a post back, and *this instrument
being wrong* — between 10-09 and 10-13 about two thirds of one
evidence type was our own fault (METHODOLOGY 8b). A third
possibility, raised by an interviewee rather than by the data, is
throttling: a post that is still there but stops being served for a
while. Nothing here distinguishes the three. What it can do is show
the exact sequence, with the evidence behind each reading, so a
person can.

Prints the account's posts, newest first. `--checks` adds every
check of every post, which is where the sequence lives.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthorPost, LinkCheck, WebAuthor, WebVideo
from .recheck import ALIVE, GONE, UNKNOWN, _BY_EVIDENCE

#: How each stored evidence reads in one word, for a dense table.
_SHORT = {
    "served another video": "served-another",
    "id confirmed": "alive",
    "page says the post is gone": "page-says-gone",
    "the site filtered the post out": "filtered",
    "read, nothing on the page": "unreadable",
}


def find_account(session: Session, who: str) -> WebAuthor | None:
    """By 抖音号, or by sec_uid. Both, because a person has the first
    in front of them and the database keys on the second."""
    row = session.scalar(
        select(WebAuthor).where(WebAuthor.author_handle == who))
    if row is not None:
        return row
    return session.scalar(select(WebAuthor).where(WebAuthor.sec_uid == who))


def posts_of(session: Session, sec_uid: str) -> list[WebVideo]:
    ids = [
        video_id for (video_id,) in session.execute(
            select(AuthorPost.video_id).where(AuthorPost.sec_uid == sec_uid))
    ]
    if not ids:
        return []
    rows = list(session.scalars(
        select(WebVideo).where(WebVideo.video_id.in_(ids))))
    rows.sort(key=lambda r: r.posted_on or datetime.min, reverse=True)
    return rows


def checks_of(session: Session, video_id: str) -> list[LinkCheck]:
    return list(session.scalars(
        select(LinkCheck)
        .where(LinkCheck.video_id == video_id)
        .order_by(LinkCheck.checked_at)
    ))


def state_of(checks: list[LinkCheck]) -> tuple[str, str]:
    """(what it is now, what the sequence looks like).

    The second is the point. "gone" and "gone, back, gone again" are
    different objects and the first word alone hides which.
    """
    if not checks:
        return "never checked", ""
    verdicts = [_BY_EVIDENCE.get(c.evidence or "", UNKNOWN) for c in checks]
    now = verdicts[-1]
    # Collapse runs: ALIVE ALIVE GONE GONE ALIVE -> alive, gone, alive
    runs: list[str] = []
    for v in verdicts:
        if v == UNKNOWN:
            continue
        if not runs or runs[-1] != v:
            runs.append(v)
    shape = " → ".join(runs)
    return now, shape


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("who", help="抖音号, or sec_uid")
    parser.add_argument("--checks", action="store_true",
                        help="every check of every post, with its evidence")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        account = find_account(session, args.who)
        if account is None:
            raise SystemExit(
                f"no account with 抖音号 or sec_uid {args.who!r}.\n"
                "The handle is only learned from a profile read; an "
                "account never read has none on file.")

        print(f"{account.author_name or '—'}  (抖音号 {account.author_handle})")
        print(f"https://www.douyin.com/user/{account.sec_uid}")
        if account.ip_location:
            print(f"profile says: {account.ip_location}")
        print()

        rows = posts_of(session, account.sec_uid)
        if not rows:
            print("no posts of this account are in the corpus")
            return

        tally: dict[str, int] = {}
        for post in rows:
            checks = checks_of(session, post.video_id)
            now, shape = state_of(checks)
            tally[now] = tally.get(now, 0) + 1

            kind = "图文" if post.platform == "douyin_note" else "视频"
            where = ("https://www.douyin.com/note/" if post.platform ==
                     "douyin_note" else "https://www.douyin.com/video/")
            when = post.posted_on.strftime("%m-%d %H:%M") if post.posted_on else "—"
            print(f"[{now}] {kind}  posted {when}  {where}{post.video_id}")
            if shape and " → " in shape:
                print(f"    sequence: {shape}")
            caption = (post.caption or "").replace("\n", " ")
            if caption:
                print(f"    {caption[:110]}")
            if post.local_path:
                print(f"    file: {post.local_path}")
            else:
                print("    file: not downloaded")

            if args.checks:
                for c in checks:
                    said = _SHORT.get(c.evidence or "", c.evidence or "—")
                    reason = f" ({c.filter_reason})" if c.filter_reason else ""
                    print(f"      {c.checked_at:%m-%d %H:%M}  {said}{reason}")
            print()

        print("--")
        for name in (GONE, ALIVE, UNKNOWN, "never checked"):
            if tally.get(name):
                print(f"{tally[name]:3} {name}")
        back = sum(1 for p in rows
                   if " → " in state_of(checks_of(session, p.video_id))[1])
        if back:
            print(f"{back:3} post(s) changed state at least once "
                  "(see 'sequence' above)")


if __name__ == "__main__":  # pragma: no cover
    main()
