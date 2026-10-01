"""Recover the accounts behind posts that were already wiped.

    ./.venv/bin/python -m app.recover_authors            # what is recoverable
    ./.venv/bin/python -m app.recover_authors --apply    # put it back

A post found gone had its contents cleared, and `sec_uid` was in that
list -- so at the moment a post disappeared, the only address that
reaches its author disappeared too. `fetch_videos.wipe` no longer does
that: the account moves to `web_authors` instead. This is for the
posts that went before the fix, and it reads them out of the daily
backups, where the row still carries the account it had the day
before it went.

The author of a removed post is who this study's interviews are for,
so this is not housekeeping. It is the recruitment frame.

Read-only on the backups, and additive on the live database: it never
overwrites an account already on file, and never touches a video row.
Dry by default.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import BACKUP_DIR
from .models import WebAuthor, WebVideo


def gone_without_an_account(session: Session) -> set[str]:
    """Video ids this database can no longer reach an author for.

    Gone, nothing on the row, and no account kept for them. A post
    still up is not here: its row still carries the account, and
    `app.fetch_authors` reaches it the ordinary way.
    """
    from .survival import findings

    held = {
        video_id
        for (video_id,) in session.execute(
            select(WebAuthor.kept_for_video_id).where(
                WebAuthor.kept_for_video_id.isnot(None)
            )
        )
    }
    live = {
        video_id
        for (video_id,) in session.execute(
            select(WebVideo.video_id).where(WebVideo.sec_uid.isnot(None))
        )
    }
    out = set()
    for finding in findings(session):
        if not finding.is_gone or not finding.video_id:
            continue
        if finding.video_id in held or finding.video_id in live:
            continue
        out.add(finding.video_id)
    return out


def from_backup(path: Path, wanted: set[str]) -> dict[str, tuple]:
    """(sec_uid, handle, name) per video id, as this backup had them.

    Opened read-only, by URI: a backup is evidence and a tool that
    reads it must not be able to write to it.
    """
    found: dict[str, tuple] = {}
    if not path.exists():
        return found
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT video_id, sec_uid, author_handle, author_name "
            "FROM web_videos WHERE sec_uid IS NOT NULL"
        )
        for video_id, sec_uid, handle, name in rows:
            if video_id in wanted and video_id not in found:
                found[video_id] = (sec_uid, handle, name)
    except sqlite3.DatabaseError:
        # A truncated copy is not a reason to stop reading the others.
        return found
    finally:
        connection.close()
    return found


def recover(
    session: Session,
    backups: Path = BACKUP_DIR,
    apply: bool = False,
) -> dict[str, tuple]:
    """What the backups can give back, newest copy first.

    Newest first because a later copy is closer to the post's own
    last reading of itself; an older one would do, but there is no
    reason to prefer it.
    """
    wanted = gone_without_an_account(session)
    if not wanted:
        return {}

    recovered: dict[str, tuple] = {}
    for path in sorted(backups.glob("scraper-*.db"), reverse=True):
        for video_id, trio in from_backup(path, wanted).items():
            if video_id not in recovered:
                recovered[video_id] = trio
        if len(recovered) == len(wanted):
            break

    if not apply:
        return recovered

    for video_id, (sec_uid, handle, name) in recovered.items():
        known = session.scalars(
            select(WebAuthor).where(WebAuthor.sec_uid == sec_uid)
        ).first()
        if known is None:
            session.add(WebAuthor(
                sec_uid=sec_uid,
                platform="douyin",
                author_handle=handle,
                author_name=name,
                kept_for_video_id=video_id,
            ))
            continue
        if known.author_handle is None and handle:
            known.author_handle = handle
        if known.author_name is None and name:
            known.author_name = name
        if known.kept_for_video_id is None:
            known.kept_for_video_id = video_id
    session.commit()
    return recovered


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the rows")
    parser.add_argument(
        "--backups", type=Path, default=BACKUP_DIR,
        help="where the daily copies are",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        missing = gone_without_an_account(session)
        recovered = recover(session, args.backups, apply=args.apply)
        print(
            f"{len(missing)} removed post(s) with no reachable author; "
            f"{len(recovered)} found in {args.backups}"
        )
        if recovered and not args.apply:
            print("Add --apply to put them back.")
        lost = sorted(missing - set(recovered))
        if lost:
            print(
                f"\n{len(lost)} not in any backup -- those posts went "
                "before a copy of the row existed:"
            )
            for video_id in lost[:20]:
                print(f"  {video_id}")
        if args.apply and recovered:
            print("\nNow read the profiles:\n  python -m app.fetch_authors --apply")


if __name__ == "__main__":  # pragma: no cover
    main()
