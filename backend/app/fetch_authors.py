"""Visit each author's profile and record the 抖音号.

    ./.venv/bin/python -m app.fetch_authors            # what is missing
    ./.venv/bin/python -m app.fetch_authors --apply    # go and get it

The handle is the one field neither the feed nor the video page
reliably gives. Douyin's feed renders a display name, which the owner
shares with anyone else who picked it and can change at will; the
抖音号 is on the profile and nowhere else. It is what finds an account
again months later, and what an interview request is addressed to, so
for a study that follows takedowns it is the field that matters most.

Run `app.fetch_videos` first: it records each video's `sec_uid`, and
that is what a profile URL is keyed on. One visit per account, not
per video -- the answer is a property of the account.

Dry by default; `--apply` fetches, pausing between requests.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .browser import AUTHOR_URL as BROWSER_AUTHOR_URL, DEFAULT_PROFILE, open_browser
from .douyin_page import AUTHOR_URL, author_facts, fetch
from .models import WebAuthor, WebVideo

PAUSE_SECONDS = 2.0


def wanted(session: Session, refresh: bool = False) -> list[str]:
    """Accounts we have a `sec_uid` for and no profile reading of."""
    known = [
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebVideo.sec_uid).where(WebVideo.sec_uid.isnot(None)).distinct()
        )
    ]
    if refresh:
        return sorted(set(known))
    already = {
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebAuthor.sec_uid).where(WebAuthor.error.is_(None))
        )
    }
    return sorted(set(known) - already)


def store(session: Session, sec_uid: str, page, facts) -> WebAuthor:
    row = session.scalars(
        select(WebAuthor).where(WebAuthor.sec_uid == sec_uid)
    ).first()
    if row is None:
        row = WebAuthor(sec_uid=sec_uid, platform="douyin")
        session.add(row)

    row.http_status = page.http_status
    row.error = page.error
    row.fetched_at = datetime.utcnow()
    if facts is not None:
        row.author_handle = facts.author_handle or row.author_handle
        row.author_name = facts.author_name or row.author_name
        row.signature = facts.signature or row.signature
        row.ip_location = facts.ip_location or row.ip_location
        for field in (
            "follower_count",
            "following_count",
            "total_favorited",
            "video_count",
        ):
            value = getattr(facts, field)
            if value is not None:
                setattr(row, field, value)
        row.parsed_by = facts.parsed_by
    session.commit()
    return row


def anonymous(sec_uid: str):
    """Ask the share host, with no session behind the request."""
    return fetch(AUTHOR_URL.format(sec_uid=sec_uid))


def through(browser, on_wall=None):
    """Read the site's own profile page in a signed-in browser."""

    def read(sec_uid: str):
        seen = browser.read(BROWSER_AUTHOR_URL.format(sec_uid=sec_uid))
        if seen.wall and on_wall is not None:
            on_wall(browser)
            seen = browser.read(BROWSER_AUTHOR_URL.format(sec_uid=sec_uid))
        return seen.fetched

    return read


def run(
    session: Session,
    sec_uids: list[str],
    pause_seconds: float = PAUSE_SECONDS,
    dump: Path | None = None,
    fetcher=anonymous,
    on_progress=None,
) -> dict[str, int]:
    report = {"read": 0, "with_handle": 0, "unreadable": 0}
    total = len(sec_uids)

    for index, sec_uid in enumerate(sec_uids):
        if index and pause_seconds:
            time.sleep(pause_seconds)

        page = fetcher(sec_uid)
        facts = author_facts(page.html) if page.html else None

        if facts is None or facts.is_empty():
            report["unreadable"] += 1
            outcome = page.error or f"HTTP {page.http_status}: nothing readable"
            if dump is not None and page.html:
                dump.mkdir(parents=True, exist_ok=True)
                (dump / f"{sec_uid[:40]}.html").write_text(page.html, encoding="utf-8")
                outcome += " -- page written out"
        else:
            report["read"] += 1
            if facts.author_handle:
                report["with_handle"] += 1
            outcome = f"{facts.author_name or '?'}  抖音号={facts.author_handle or '—'}"

        store(session, sec_uid, page, facts)
        if on_progress:
            on_progress(index + 1, total, outcome)

    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="fetch; otherwise count and stop")
    parser.add_argument("--limit", type=int, default=None, help="stop after N accounts")
    parser.add_argument("--refresh", action="store_true", help="re-read profiles already read")
    parser.add_argument("--pause", type=float, default=PAUSE_SECONDS)
    parser.add_argument("--dump", default="", help="directory for pages that could not be read")
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help=(
            "ask the share host with no session, instead of a signed-in "
            "browser -- lighter, but reads far less"
        ),
    )
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument(
        "--headless",
        action="store_true",
        help="no window; a verification page then cannot be answered",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        targets = wanted(session, refresh=args.refresh)
        if args.limit is not None:
            targets = targets[: args.limit]

        if not args.apply:
            print(
                f"{len(targets):,} profile(s) to read. Add --apply to fetch them.\n"
                "Run app.fetch_videos first if this is zero -- the sec_uid "
                "comes from the video pages."
            )
            return

        def show(done: int, total: int, outcome: str) -> None:
            print(f"[{done}/{total}] {outcome}", flush=True)

        if args.anonymous:
            report = run(
                session,
                targets,
                pause_seconds=args.pause,
                dump=Path(args.dump) if args.dump else None,
                fetcher=anonymous,
                on_progress=show,
            )
        else:
            # A signed-in browser, and a stop rather than a retry when
            # the site asks for a person. Hammering a challenge is how
            # a session turns into a block.
            def on_wall(browser) -> None:
                browser.wait_for_person("Douyin is asking to sign in or verify.")

            with open_browser(
                Path(args.profile),
                headless=args.headless,
                pause_seconds=args.pause,
            ) as browser:
                report = run(
                    session,
                    targets,
                    pause_seconds=0,  # the browser paces itself
                    dump=Path(args.dump) if args.dump else None,
                    fetcher=through(browser, on_wall=None if args.headless else on_wall),
                    on_progress=show,
                )
        print(
            f"read {report['read']} profile(s), {report['with_handle']} with a "
            f"抖音号; {report['unreadable']} unreadable"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
