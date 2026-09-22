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

from dataclasses import dataclass
from typing import Callable

from .clock import now as utc_now
from .browser import (
    VIDEO_URL as BROWSER_VIDEO_URL,
    DEFAULT_PROFILE,
    HOMES,
    PROFILES,
    open_browser,
)
from .models import LinkCheck
from . import douyin_page, tiktok_page
from .recheck import ID_CONFIRMED, SERVED_ANOTHER
from .models import SharedLink, WebVideo


@dataclass(frozen=True)
class Site:
    """What differs between the two platforms, and nothing else.

    The parts worth sharing are the ones that took a mistake to get
    right: verifying that the record is about the video asked for,
    emptying a row whose contents turned out to be another video's,
    and filing each fetch as a takedown check. Those are the same on
    both sites, so they are written once and this table carries the
    differences -- the address, the field names, and whether a signed
    -in session is required or merely better.
    """

    platform: str
    #: (html, payloads) -> VideoFacts
    facts: Callable
    #: (video_id, handle) -> the URL to open in the browser
    page_url: Callable
    #: (video_id, handle) -> the URL to try with no session at all
    share_url: Callable
    #: Douyin answers an anonymous request with a download wall, so a
    #: session is the only way in. TikTok mostly answers, so a missing
    #: session is worth saying and not worth refusing over.
    needs_session: bool


SITES: dict[str, Site] = {
    "douyin": Site(
        platform="douyin",
        facts=douyin_page.video_facts,
        page_url=lambda video_id, handle: BROWSER_VIDEO_URL.format(
            video_id=video_id
        ),
        share_url=lambda video_id, handle: douyin_page.VIDEO_URL.format(
            video_id=video_id
        ),
        needs_session=True,
    ),
    "tiktok": Site(
        platform="tiktok",
        facts=tiktok_page.video_facts,
        page_url=lambda video_id, handle: tiktok_page.video_url(video_id, handle),
        share_url=lambda video_id, handle: tiktok_page.video_url(video_id, handle),
        needs_session=False,
    ),
}

#: Seconds between requests. Same reasoning as `app/resolve.py`.
PAUSE_SECONDS = 2.0


def wanted(
    session: Session, platform: str = "douyin", refresh: bool = False
) -> list[str]:
    """Video ids we hold a link for and have not read the page of."""
    ids = [
        video_id
        for (video_id,) in session.execute(
            select(SharedLink.video_id)
            .where(SharedLink.platform == platform, SharedLink.video_id.isnot(None))
            .distinct()
        )
    ]
    if refresh:
        return sorted(set(ids))
    already = {
        video_id
        for (video_id,) in session.execute(
            select(WebVideo.video_id).where(
                WebVideo.error.is_(None), WebVideo.platform == platform
            )
        )
    }
    return sorted(set(ids) - already)


def handles(session: Session, platform: str) -> dict[str, str]:
    """The @handle each id's link carried, where it carried one.

    TikTok puts it in the address -- `/@name/video/<id>` -- and the
    page is reached without it only by redirect, so the link's own
    handle is worth using when there is one. Douyin's addresses have
    no handle in them and this is simply empty there.
    """
    found: dict[str, str] = {}
    for video_id, handle in session.execute(
        select(SharedLink.video_id, SharedLink.author_handle).where(
            SharedLink.platform == platform,
            SharedLink.video_id.isnot(None),
            SharedLink.author_handle.isnot(None),
        )
    ):
        found.setdefault(video_id, (handle or "").lstrip("@"))
    return {video_id: handle for video_id, handle in found.items() if handle}


def record_check(
    session: Session,
    video_id: str,
    page,
    evidence: str,
    url: str,
    platform: str = "douyin",
) -> None:
    """File this fetch as a check, so removals reach the findings.

    A browser signed in to the site is a better probe than the
    anonymous fetch `app.recheck` makes: Douyin answers that one with
    a download wall, which is no evidence either way. Here the
    exchange either returns the video asked for or it does not, and
    that is what gets recorded.
    """
    session.add(
        LinkCheck(
            platform=platform,
            target_kind="video",
            video_id=video_id,
            url=url,
            checked_at=utc_now(),
            http_status=page.http_status,
            final_url=None,
            error=page.error,
            evidence=evidence,
        )
    )
    session.commit()


#: Fields that describe the video itself, as opposed to the fetch.
_CONTENT = (
    "sec_uid",
    "author_name",
    "author_handle",
    "caption",
    "posted_on",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
)


def wipe(session: Session, video_id: str, page, platform: str = "douyin") -> None:
    """Empty a row whose contents turned out to be another video's.

    A mismatch used to leave the fields alone, which meant a row
    written before the id was checked kept them: the removed video
    `7686427432119291057` went on showing Johnny Dear, his 449,443
    likes and his 抖音号 long after the check beside it said `gone`.
    Nothing here belongs to this id, so none of it stays.
    """
    row = session.scalars(
        select(WebVideo).where(WebVideo.video_id == video_id)
    ).first()
    if row is None:
        row = WebVideo(video_id=video_id, platform=platform)
        session.add(row)
    for field in _CONTENT:
        setattr(row, field, None)
    row.http_status = page.http_status
    row.error = page.error
    row.parsed_by = None
    row.fetched_at = utc_now()
    session.commit()


def store(
    session: Session, video_id: str, page, facts, platform: str = "douyin"
) -> WebVideo:
    row = session.scalars(
        select(WebVideo).where(WebVideo.video_id == video_id)
    ).first()
    if row is None:
        row = WebVideo(video_id=video_id, platform=platform)
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


def anonymous(url: str):
    """Ask for the page with no session behind the request."""
    if "douyin" in url:
        return douyin_page.fetch(url)
    return tiktok_page.fetch(url)


def through(browser, on_wall=None):
    """Read the site's own page in a signed-in browser."""

    def read(url: str):
        seen = browser.read(url)
        if seen.wall and on_wall is not None:
            on_wall(browser)
            seen = browser.read(url)
        return seen.fetched

    return read


def run(
    session: Session,
    video_ids: list[str],
    pause_seconds: float = PAUSE_SECONDS,
    dump: Path | None = None,
    fetcher=anonymous,
    on_progress=None,
    site: Site | None = None,
    handle_for: dict[str, str] | None = None,
) -> dict[str, int]:
    site = site or SITES["douyin"]
    handle_for = handle_for or {}
    report = {"read": 0, "surface_only": 0, "unreadable": 0, "served_another": 0}
    total = len(video_ids)

    for index, video_id in enumerate(video_ids):
        if index and pause_seconds:
            time.sleep(pause_seconds)

        url = site.page_url(video_id, handle_for.get(video_id))
        page = fetcher(url)
        facts = (
            site.facts(page.html or "", page.payloads)
            if (page.html or page.payloads)
            else None
        )

        # The record has to be the one that was asked for. Douyin
        # answers a request for a removed video by playing the next
        # recommended one, and its API response describes that video:
        # status 200, no removal wording, someone else's caption and
        # counts. One run filed "Johnny Dear -- 第一颗纽扣错了" under
        # the id of a video that was gone.
        if facts is not None and facts.video_id and facts.video_id != video_id:
            record_check(
                session, video_id, page, SERVED_ANOTHER, url, site.platform
            )
            report["served_another"] += 1
            wipe(session, video_id, page, site.platform)
            if on_progress:
                on_progress(
                    index + 1,
                    total,
                    f"gone -- the site served {facts.video_id} instead",
                )
            continue

        if facts is not None and not facts.is_empty():
            record_check(
                session,
                video_id,
                page,
                ID_CONFIRMED if facts.video_id == video_id else "",
                url,
                site.platform,
            )

        if facts is None or facts.is_empty():
            report["unreadable"] += 1
            outcome = page.error or f"HTTP {page.http_status}: nothing readable"
            if dump is not None and page.html:
                dump.mkdir(parents=True, exist_ok=True)
                (dump / f"{video_id}.html").write_text(page.html, encoding="utf-8")
                outcome += f" -- wrote {video_id}.html"
        else:
            report["read"] += 1
            outcome = (
                f"{facts.author_name or '?'} | {(facts.caption or '')[:36]}"
            )
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


        store(session, video_id, page, facts, site.platform)
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
    parser.add_argument(
        "--platform",
        default="douyin",
        choices=sorted(SITES),
        help="which site's pages to read",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="browser profile directory; defaults to one per platform",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="no window; a verification page then cannot be answered",
    )
    args = parser.parse_args()

    site = SITES[args.platform]
    profile = Path(args.profile) if args.profile else PROFILES[args.platform]

    init_db()
    with SessionLocal() as session:
        targets = wanted(session, args.platform, refresh=args.refresh)
        handle_for = handles(session, args.platform)
        if args.limit is not None:
            targets = targets[: args.limit]

        if not args.apply:
            print(
                f"{len(targets):,} {args.platform} video page(s) to read. "
                "Add --apply to fetch them."
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
                site=site,
                handle_for=handle_for,
            )
        else:
            # A signed-in browser, and a stop rather than a retry when
            # the site asks for a person. Hammering a challenge is how
            # a session turns into a block.
            def on_wall(browser) -> None:
                browser.wait_for_person(
                    f"{args.platform} is asking to sign in or verify."
                )

            with open_browser(
                profile,
                headless=args.headless,
                pause_seconds=args.pause,
                platform=args.platform,
            ) as browser:
                # Check the session once, here, rather than discovering
                # it missing on every page. A run that asks to sign in
                # at each of two hundred videos is a run with no
                # session at all, and saying so once is the useful
                # thing to do.
                browser.read(HOMES[args.platform], settle_seconds=1.0)
                if not browser.is_signed_in():
                    message = (
                        f"No saved session in {profile}. Sign in once first:\n"
                        f"    ./.venv/bin/python -m app.login "
                        f"--platform {args.platform}"
                    )
                    if site.needs_session:
                        # Douyin answers an anonymous request with a
                        # download wall, so there is nothing to read
                        # without one and starting would waste the run.
                        print(
                            message
                            + "\nOr pass --anonymous to read what the share "
                            "host gives without one."
                        )
                        return
                    # TikTok mostly answers without one. Worth saying,
                    # not worth refusing over.
                    print(
                        f"No saved session in {profile}; reading signed out.\n"
                        f"{message}\n"
                    )

                report = run(
                    session,
                    targets,
                    pause_seconds=0,  # the browser paces itself
                    dump=Path(args.dump) if args.dump else None,
                    fetcher=through(browser, on_wall=None if args.headless else on_wall),
                    on_progress=show,
                    site=site,
                    handle_for=handle_for,
                )
        print(
            f"read {report['read']}, of which {report['surface_only']} "
            f"only off the surface; {report['unreadable']} unreadable; "
            f"{report['served_another']} gone (the site served another video)"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
