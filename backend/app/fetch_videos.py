"""Visit each collected video's own page and record what it says.

    ./.venv/bin/python -m app.fetch_videos            # what is missing
    ./.venv/bin/python -m app.fetch_videos --apply    # go and get it

The phone's job ends at the link. It can reach posts the web search
will not return, which is why it collects at all, but what it reads
off a feed has to be stitched to a link afterwards -- and that stitch
is where every wrong row in this study came from.

A page fetched from the video's own URL needs no stitch: the id is in
the address. So the caption, the author, the counts and the exact
publication time all arrive already attached to the right video, and
`web_videos` becomes the authority for them.

Dry by default: it says how many pages it would fetch and stops.
`--apply` fetches, pausing between requests -- a study that gets
itself blocked has lost observations it cannot go back for.
`--dump DIR` writes the HTML of any page it could not read, which is
what turns a guessed selector into a known one.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as utc_now
from .browser import VIDEO_URL as BROWSER_VIDEO_URL, DEFAULT_PROFILE, open_browser
from .douyin_page import VIDEO_URL, fetch, video_facts
from .models import SharedLink, WebVideo

#: Seconds between requests. Same reasoning as `app/resolve.py`.
PAUSE_SECONDS = 2.0


def wanted(session: Session, refresh: bool = False) -> list[str]:
    """Video ids we hold a link for and have not read the page of."""
    ids = [
        video_id
        for (video_id,) in session.execute(
            select(SharedLink.video_id)
            .where(SharedLink.platform == "douyin", SharedLink.video_id.isnot(None))
            .distinct()
        )
    ]
    if refresh:
        return sorted(set(ids))
    already = {
        video_id
        for (video_id,) in session.execute(
            select(WebVideo.video_id).where(WebVideo.error.is_(None))
        )
    }
    return sorted(set(ids) - already)


def store(session: Session, video_id: str, page, facts) -> WebVideo:
    row = session.scalars(
        select(WebVideo).where(WebVideo.video_id == video_id)
    ).first()
    if row is None:
        row = WebVideo(video_id=video_id, platform="douyin")
        session.add(row)

    row.http_status = page.http_status
    row.error = page.error
    row.fetched_at = utc_now()
    if facts is not None:
        row.sec_uid = facts.sec_uid or row.sec_uid
        row.author_name = facts.author_name or row.author_name
        row.author_handle = facts.author_handle or row.author_handle
        row.caption = facts.caption or row.caption
        row.posted_on = facts.posted_on or row.posted_on
        row.like_count = facts.like_count if facts.like_count is not None else row.like_count
        row.comment_count = (
            facts.comment_count if facts.comment_count is not None else row.comment_count
        )
        row.share_count = (
            facts.share_count if facts.share_count is not None else row.share_count
        )
        row.collect_count = (
            facts.collect_count if facts.collect_count is not None else row.collect_count
        )
        row.parsed_by = facts.parsed_by
    session.commit()
    return row


def anonymous(video_id: str):
    """Ask the share host, with no session behind the request."""
    return fetch(VIDEO_URL.format(video_id=video_id))


def through(browser, on_wall=None):
    """Read the site's own page in a signed-in browser."""

    def read(video_id: str):
        seen = browser.read(BROWSER_VIDEO_URL.format(video_id=video_id))
        if seen.wall and on_wall is not None:
            on_wall(browser)
            seen = browser.read(BROWSER_VIDEO_URL.format(video_id=video_id))
        return seen.fetched

    return read


def run(
    session: Session,
    video_ids: list[str],
    pause_seconds: float = PAUSE_SECONDS,
    dump: Path | None = None,
    fetcher=anonymous,
    on_progress=None,
) -> dict[str, int]:
    report = {"read": 0, "surface_only": 0, "unreadable": 0}
    total = len(video_ids)

    for index, video_id in enumerate(video_ids):
        if index and pause_seconds:
            time.sleep(pause_seconds)

        page = fetcher(video_id)
        facts = video_facts(page.html) if page.html else None

        if facts is None or facts.is_empty():
            report["unreadable"] += 1
            outcome = page.error or f"HTTP {page.http_status}: nothing readable"
            if dump is not None and page.html:
                dump.mkdir(parents=True, exist_ok=True)
                (dump / f"{video_id}.html").write_text(page.html, encoding="utf-8")
                outcome += f" -- wrote {video_id}.html"
        else:
            report["read"] += 1
            outcome = f"{facts.author_name or '?'} | {(facts.caption or '')[:36]}"
            if facts.parsed_by == "surface":
                report["surface_only"] += 1
                # The interesting failure now. A page read off its
                # surface yields a caption and a date and no counts,
                # and looks like a success in the tally -- so it is
                # written out too, and says so on its line.
                outcome += "  [surface only]"
                if dump is not None and page.html:
                    dump.mkdir(parents=True, exist_ok=True)
                    (dump / f"{video_id}.surface.html").write_text(
                        page.html, encoding="utf-8"
                    )
                    outcome += f" -- wrote {video_id}.surface.html"


        store(session, video_id, page, facts)
        if on_progress:
            on_progress(index + 1, total, outcome)

    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="fetch; otherwise count and stop")
    parser.add_argument("--limit", type=int, default=None, help="stop after N videos")
    parser.add_argument("--refresh", action="store_true", help="re-read pages already read")
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
            print(f"{len(targets):,} video page(s) to read. Add --apply to fetch them.")
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
                # Check the session once, here, rather than discovering
                # it missing on every page. A run that asks to sign in
                # at each of two hundred videos is a run with no
                # session at all, and saying so once is the useful
                # thing to do.
                browser.read("https://www.douyin.com/", settle_seconds=1.0)
                if not browser.is_signed_in():
                    print(
                        "No saved session in "
                        f"{args.profile}. Sign in once first:\n"
                        "    ./.venv/bin/python -m app.login\n"
                        "Or pass --anonymous to read what the share host "
                        "gives without one."
                    )
                    return

                report = run(
                    session,
                    targets,
                    pause_seconds=0,  # the browser paces itself
                    dump=Path(args.dump) if args.dump else None,
                    fetcher=through(browser, on_wall=None if args.headless else on_wall),
                    on_progress=show,
                )
        print(
            f"read {report['read']}, of which {report['surface_only']} "
            f"only off the surface; {report['unreadable']} unreadable"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
