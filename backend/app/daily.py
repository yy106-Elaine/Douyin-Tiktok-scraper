"""One pass per video: read the page, record it, keep the file.

    ./.venv/bin/python -m app.daily --platform douyin           # what it would do
    ./.venv/bin/python -m app.daily --platform douyin --apply

This is `app.fetch_videos --refresh` followed by `app.download_videos`
in a single pass, and the reason is not tidiness. Run separately, each
video's page is opened twice: once to read the caption, the author and
whether the id still matches, and again to find the file addresses.
The addresses are already in the answer the first visit got. So the
second visit buys nothing and costs a page load, a pause and one more
request against a site that is counting them -- about half of a run
that takes an hour for 177 videos.

The order inside one video matters. The id is checked before anything
is downloaded: Douyin answers a request for a removed video by serving
the next recommended one, so without that check the folder fills with
other people's videos filed under the ids of the removed ones -- worse
than a gap, because it is a gap that looks full. A video found gone is
recorded as gone and not downloaded; there is nothing there to fetch.

What this does not do is collect. The phone collects, and nothing here
touches it.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from sqlalchemy.orm import Session

from .browser import HOMES, PROFILES, open_browser
from .download_videos import (
    default_dir,
    held,
    looks_like_video,
    record,
    save,
    write_manifest,
)
from .fetch_videos import (
    SITES,
    handles,
    record_check,
    store,
    through,
    wanted,
    wipe,
)
from .platforms import filter_policy
from .recheck import ID_CONFIRMED, SERVED_ANOTHER
from .relevance import HIDDEN, classify


def one(
    session: Session,
    read,
    download,
    video_id: str,
    site,
    handle: str | None,
    directory: Path,
    redownload: bool = False,
    keep_all: bool = False,
) -> tuple[str, str, int]:
    """Settle one video. Returns (outcome, description, bytes kept).

    `read` takes a URL and returns a `Fetched`; `download` takes a URL
    and a referer and returns (bytes, status). Both are injected so
    this is testable without a browser, and so the caller decides
    whether the requests carry a session.
    """
    url = site.page_url(video_id, handle)
    page = read(url)
    facts = (
        site.facts(page.html or "", page.payloads)
        if (page.html or page.payloads)
        else None
    )

    # Gone: the site answered with a different video's record. Recorded
    # and not downloaded.
    if facts is not None and facts.video_id and facts.video_id != video_id:
        record_check(session, video_id, page, SERVED_ANOTHER, url, site.platform)
        wipe(session, video_id, page, site.platform)
        return "gone", f"gone -- the site served {facts.video_id} instead", 0

    if facts is None or facts.is_empty():
        return (
            "unreadable",
            page.error or f"HTTP {page.http_status}: nothing readable",
            0,
        )

    record_check(
        session,
        video_id,
        page,
        ID_CONFIRMED if facts.video_id == video_id else "",
        url,
        site.platform,
    )
    row = store(session, video_id, page, facts, site.platform)
    said = f"{facts.author_name or '?'} | {(facts.caption or '')[:36]}"
    if facts.parsed_by == "surface":
        said += "  [surface only]"

    # Whether to keep the file is decided here, after the page has
    # been read and not before. The phone's caption is what the
    # interface rendered and is often cut off mid-word; the page's is
    # the authority, and it is the reason the page is fetched. Judging
    # a never-read video on the screen text would drop videos that the
    # full caption puts squarely in the corpus.
    #
    # The page visit itself is never skipped: that visit *is* the
    # takedown check, and a video excluded today may be back in the
    # corpus tomorrow when a rule changes -- which has happened
    # repeatedly. What is skipped is the copy. `#butchfemme
    # #femme4butch #lesbiansoftiktok` is somebody's video and not this
    # study's subject; there is no call to hold it.
    reason = classify(facts.caption or "", policy=filter_policy(site.platform))
    if reason in HIDDEN and not keep_all:
        return "read", f"{said}  [not kept: {reason}]", 0

    # The file, out of the answer already in hand.
    if not redownload and held(row):
        return "read", f"{said}  [file held]", 0

    addresses = site.file_urls(page.html or "", page.payloads, video_id=video_id)
    if not addresses:
        record(session, row, None, None, "no file address for this id")
        return "read", f"{said}  -- no file address", 0

    last = "no url answered"
    for address in addresses:
        blob, status = download(address, url)
        if blob is None:
            last = str(status)
            continue
        if not looks_like_video(blob):
            # A media URL fetched without the right session answers 200
            # with an error page. Saved as .mp4 it gives a folder that
            # looks complete and a corpus that is not, discovered at the
            # point of analysis, when the video is gone.
            last = f"not a video ({len(blob)} bytes, http {status})"
            continue
        path = save(directory, video_id, blob)
        record(session, row, path, blob, None)
        return "saved", f"{said}  {len(blob) / 1_000_000:.1f} MB", len(blob)

    record(session, row, None, None, last)
    return "read", f"{said}  -- {last}", 0


def run(
    session: Session,
    video_ids: list[str],
    read,
    download,
    directory: Path,
    site,
    handle_for: dict[str, str] | None = None,
    pause_seconds: float = 0.0,
    redownload: bool = False,
    keep_all: bool = False,
    on_progress=None,
) -> dict[str, int]:
    handle_for = handle_for or {}
    report = {"read": 0, "saved": 0, "gone": 0, "unreadable": 0, "bytes": 0}
    total = len(video_ids)
    for index, video_id in enumerate(video_ids):
        if index and pause_seconds:
            time.sleep(pause_seconds)
        outcome, said, kept = one(
            session,
            read,
            download,
            video_id,
            site,
            handle_for.get(video_id),
            directory,
            redownload=redownload,
            keep_all=keep_all,
        )
        report[outcome] = report.get(outcome, 0) + 1
        report["bytes"] += kept
        # A saved video was also read: the page visit that produced the
        # file is the same visit that confirmed the id.
        if outcome == "saved":
            report["read"] += 1
        if on_progress:
            on_progress(index + 1, total, said)
    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform", default="douyin", choices=sorted(SITES),
        help="which platform's videos to read and keep",
    )
    parser.add_argument("--apply", action="store_true", help="actually do it")
    parser.add_argument("--limit", type=int, default=None, help="stop after N videos")
    parser.add_argument(
        "--new-only",
        action="store_true",
        help=(
            "only videos whose page has never been read. The default is "
            "every video, which is what makes this the daily re-check"
        ),
    )
    parser.add_argument(
        "--skip-gone",
        action="store_true",
        help=(
            "leave out videos already found gone. A removal reversed then "
            "goes unseen, which is the cost of not spending a visit on "
            "every video that has already disappeared"
        ),
    )
    parser.add_argument(
        "--everything",
        action="store_true",
        help=(
            "keep a copy of videos the topic filter excluded too. Their "
            "pages are read either way -- that visit is the takedown "
            "check -- but by default only the corpus is downloaded"
        ),
    )
    parser.add_argument(
        "--redownload",
        action="store_true",
        help="fetch the file again even where one is already held",
    )
    parser.add_argument("--dir", type=Path, default=None, help="where the files go")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--pause", type=float, default=0.0,
        help="extra seconds between videos; the browser already paces itself",
    )
    args = parser.parse_args()

    site = SITES[args.platform]
    directory = args.dir or default_dir(args.platform)
    profile = args.profile or PROFILES[args.platform]

    init_db()
    with SessionLocal() as session:
        targets = wanted(session, args.platform, refresh=not args.new_only)

        if args.skip_gone:
            from .recheck import disappeared

            gone = disappeared(session)
            before = len(targets)
            targets = [v for v in targets if v not in gone]
            if before != len(targets):
                print(f"skipping {before - len(targets)} already found gone")

        if args.limit is not None:
            targets = targets[: args.limit]

        if not targets:
            print("nothing to do. Collect on the phone first.")
            return

        if not args.apply:
            print(
                f"{len(targets):,} {args.platform} video(s): one page visit each, "
                f"recording what it says and keeping the file in {directory}.\n"
                "Add --apply to do it."
            )
            return

        def show(done: int, total: int, said: str) -> None:
            print(f"[{done}/{total}] {said}", flush=True)

        def on_wall(browser) -> None:
            browser.wait_for_person(
                f"{args.platform} is asking to sign in or verify."
            )

        with open_browser(
            profile,
            headless=args.headless,
            pause_seconds=0,
            platform=args.platform,
        ) as browser:
            # Checked once, here. A run that asks to sign in at each of
            # two hundred videos is a run with no session at all, and
            # saying so once is the useful thing to do.
            browser.read(HOMES[args.platform], settle_seconds=1.0)
            if not browser.is_signed_in():
                message = (
                    f"No saved session in {profile}. Sign in once first:\n"
                    f"    ./.venv/bin/python -m app.login "
                    f"--platform {args.platform}"
                )
                if site.needs_session:
                    # Douyin answers an anonymous request with a wall, so
                    # there is nothing to read and starting wastes the run.
                    raise SystemExit(message)
                print(f"{message}\n(carrying on signed out)\n")

            report = run(
                session,
                targets,
                read=through(browser, on_wall=None if args.headless else on_wall),
                download=lambda address, referer: browser.download(
                    address, referer=referer
                ),
                directory=directory,
                site=site,
                handle_for=handles(session, args.platform),
                pause_seconds=args.pause,
                redownload=args.redownload,
                keep_all=args.everything,
                on_progress=show,
            )

        manifest = write_manifest(session, directory, args.platform)
        print(
            f"\nread {report['read']}; saved {report['saved']} file(s) "
            f"({report['bytes'] / 1_000_000_000:.2f} GB); "
            f"{report['gone']} gone (the site served another video); "
            f"{report['unreadable']} unreadable\n"
            f"files in {directory}\nmanifest {manifest}"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
