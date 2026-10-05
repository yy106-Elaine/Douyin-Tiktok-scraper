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
    looks_like_image,
    looks_like_video,
    record,
    save,
    save_image,
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
    author=None,
) -> tuple[str, str, int]:
    """Settle one video. Returns (outcome, description, bytes kept).

    `read` takes a URL and returns a `Fetched`; `download` takes a URL
    and a referer and returns (bytes, status). Both are injected so
    this is testable without a browser, and so the caller decides
    whether the requests carry a session.

    `author`, if given, is called with the post's account id once the
    post has been read and found to be in the corpus. It reads the
    account's profile for the 抖音号 -- the one field no video page
    carries, and the one an interview request is addressed to. It runs
    here rather than in a pass of its own so that the account is read
    while the post that points at it is still in hand: after a
    removal, a row's author fields are gone, and before this the
    handle was collected days later or not at all. It is called after
    the topic filter, never before, so a post the filter excludes
    costs no profile reading of a person who is not in this study.
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
        # Read before the row is emptied: the account is what `wipe`
        # moves aside and what the interviews are for.
        gone_author = _account(session, video_id)
        wipe(session, video_id, page, site.platform)
        said = f"gone -- the site served {facts.video_id} instead"
        if author is not None and gone_author:
            said += f"; {author(gone_author)}"
        return "gone", said, 0

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
    # One asymmetry, shared with `download_videos.wanted`: a video with
    # no caption at all is kept. "no text" is not a finding that the
    # video is off topic, it is the filter saying it cannot tell, and
    # the cost of the two mistakes is not the same. A file wrongly kept
    # can be deleted at any time; a file wrongly skipped cannot be
    # fetched again once the video is gone, and a fifth of the Douyin
    # rows have no caption.
    caption = (facts.caption or "").strip()
    reason = classify(caption, policy=filter_policy(site.platform))
    if caption and reason in HIDDEN and not keep_all:
        return "read", f"{said}  [not kept: {reason}]", 0

    # In the corpus, so the account belongs on file by name as well as
    # by id. One visit per account: the hook skips an account whose
    # 抖音号 is already known.
    if author is not None and facts.sec_uid:
        told = author(facts.sec_uid, facts.author_handle, facts.author_name)
        if told:
            said += f"  [{told}]"

    # The file, out of the answer already in hand.
    if not redownload and held(row):
        return "read", f"{said}  [file held]", 0

    addresses = site.file_urls(page.html or "", page.payloads, video_id=video_id)
    if not addresses:
        what = "image" if site.kind == "images" else "file"
        record(session, row, None, None, f"no {what} address for this id")
        return "read", f"{said}  -- no {what} address", 0

    if site.kind == "images":
        return _keep_images(session, row, download, url, video_id, directory,
                            addresses, said)

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


def _account(session: Session, video_id: str) -> str | None:
    """The account id already on file for a post, before it is cleared."""
    from sqlalchemy import select

    from .models import WebVideo

    return session.scalar(
        select(WebVideo.sec_uid).where(WebVideo.video_id == video_id)
    )


def _keep_images(
    session: Session, row, download, url: str, video_id: str,
    directory: Path, groups: list[list[str]], said: str,
) -> tuple[str, str, int]:
    """Every picture of one 图文 post, or the post is not archived.

    `groups` is one list per picture, each holding mirrors of that
    same picture. So the inner loop stops at the first mirror that
    answers and the outer loop must not stop at all: a post kept
    without its third card is a post whose meaning may be missing,
    and unlike a video there is no partial file to notice later.

    A post that loses even one picture is recorded as an error rather
    than as held, so the next pass tries again while the post is still
    there. That is the asymmetry the whole archive rests on -- a
    removal destroys the evidence, and the copy cannot be made after.
    """
    kept: list[Path] = []
    blobs: list[bytes] = []
    for index, mirrors in enumerate(groups, start=1):
        last = "no url answered"
        for address in mirrors:
            blob, status = download(address, url)
            if blob is None:
                last = str(status)
                continue
            if not looks_like_image(blob):
                last = f"not an image ({len(blob)} bytes, http {status})"
                continue
            kept.append(save_image(directory, video_id, index, blob))
            blobs.append(blob)
            break
        else:
            record(
                session, row, None, None,
                f"image {index} of {len(groups)}: {last}",
            )
            return "read", f"{said}  -- image {index}/{len(groups)}: {last}", 0

    total = sum(len(b) for b in blobs)
    # The row points at the folder, and the hash covers the pictures
    # in the post's own order -- one value that changes if any card
    # changes, is added or is reordered.
    record(session, row, kept[0].parent, b"".join(blobs), None)
    row.file_bytes = total
    session.commit()
    return "saved", f"{said}  {len(kept)} image(s), {total / 1_000_000:.1f} MB", total


def authors(session: Session, read_profile) -> "object":
    """A hook for `one`: read this account's profile if it is new.

    `read_profile` takes a sec_uid and returns a `Fetched`, the same
    shape `app.fetch_authors` uses, so this works with a signed-in
    browser or with the anonymous share host.

    Accounts already carrying a 抖音号 are skipped, so the cost is one
    profile load per *new* account in the day's collection rather than
    one per post. The handle itself never changes under an account, so
    there is nothing to refresh -- `app.fetch_authors --refresh` is
    for when the follower counts are wanted again.
    """
    from .fetch_authors import needs_reading, note, read_one

    seen: set[str] = set()
    #: What the profile visits cost this pass, reported at the end.
    #: A page visit inside a loop that has a thousand of them is the
    #: kind of cost that hides, so it is counted rather than guessed.
    spent = {"visits": 0, "seconds": 0.0}

    def visit(
        sec_uid: str,
        author_handle: str | None = None,
        author_name: str | None = None,
    ) -> str:
        if not sec_uid or sec_uid in seen:
            return ""
        seen.add(sec_uid)
        # What the post's own page said goes on file first, with no
        # request: it is sometimes the 抖音号 itself, and then there is
        # nothing on the profile to go and get.
        note(session, sec_uid, author_handle, author_name)
        if not needs_reading(session, sec_uid):
            return ""
        started = time.monotonic()
        outcome, said = read_one(session, sec_uid, fetcher=read_profile)
        spent["visits"] += 1
        spent["seconds"] += time.monotonic() - started
        return said

    visit.spent = spent  # type: ignore[attr-defined]
    return visit


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
    author=None,
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
            author=author,
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
        "--only",
        metavar="VIDEO_ID",
        action="append",
        help=(
            "this video and no other. Repeatable. For going back to one "
            "video on purpose -- a reinstatement to re-download and "
            "compare against the archived copy before it goes again"
        ),
    )
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
        "--skip-recent",
        type=float,
        metavar="HOURS",
        default=None,
        help=(
            "leave out videos already checked within this many hours. "
            "This is how an interrupted pass is resumed: a run over two "
            "hundred pages takes an hour, a network that drops takes it "
            "with it, and starting again from the top costs the hour "
            "over again -- the page visit is the expensive part, and a "
            "video already visited today has already been measured. "
            "Use 12 to carry on with what a morning's run did not reach"
        ),
    )
    parser.add_argument(
        "--unarchived", "--surface-only",
        dest="unarchived",
        action="store_true",
        help=(
            "only the posts that were read but never archived. Two ways "
            "that happens and neither leaves a mark --new-only can see: "
            "Douyin answers with a page carrying the caption in its meta "
            "tags and no data, so there are no file addresses; or the "
            "addresses were there and the download failed. Either way "
            "the row exists, so --new-only skips it from then on, and "
            "the copy is never made. This is how to go back for them"
        ),
    )
    parser.add_argument(
        "--redownload",
        action="store_true",
        help="fetch the file again even where one is already held",
    )
    parser.add_argument(
        "--no-authors",
        dest="authors",
        action="store_false",
        help=(
            "do not read the profile of a new account in the same pass. "
            "The 抖音号 is then collected later by app.fetch_authors, or "
            "not at all -- which is how months of the collection ended "
            "up with no handle for the authors it most needs. Use this "
            "only to keep a pass short; Douyin only either way"
        ),
    )
    parser.add_argument("--dir", type=Path, default=None, help="where the files go")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="rewrite this HTML page from the collection when the pass ends",
    )
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

        if args.only:
            asked = set(args.only)
            targets = [v for v in targets if v in asked]
            missing = asked - set(targets)
            if missing:
                # Named and not held: say so rather than printing
                # "nothing to do", which reads as "already done".
                print(f"not in this platform's corpus: {', '.join(sorted(missing))}")

        if args.skip_recent:
            from datetime import timedelta

            from sqlalchemy import func, select

            from .clock import now as utc_now
            from .models import LinkCheck

            cutoff = utc_now() - timedelta(hours=args.skip_recent)
            done = {
                video_id
                for (video_id,) in session.execute(
                    select(LinkCheck.video_id)
                    .where(LinkCheck.platform == args.platform)
                    .group_by(LinkCheck.video_id)
                    .having(func.max(LinkCheck.checked_at) >= cutoff)
                )
                if video_id
            }
            before = len(targets)
            targets = [v for v in targets if v not in done]
            print(
                f"skipping {before - len(targets)} checked in the last "
                f"{args.skip_recent:g}h"
            )

        if args.unarchived:
            from sqlalchemy import or_, select

            from .models import WebVideo

            missed = {
                video_id
                for (video_id,) in session.execute(
                    select(WebVideo.video_id).where(
                        WebVideo.platform == args.platform,
                        or_(
                            WebVideo.parsed_by == "surface",
                            WebVideo.download_error.isnot(None),
                        ),
                    )
                )
            }
            targets = [v for v in targets if v in missed]
            print(f"{len(targets)} read before but not archived")

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

        # Before an hour of writing: there is one copy of this
        # database and no other. `daily.sh` has always taken one and a
        # hand-run pass did not, which is backwards -- this is the long
        # pass.
        from .db import snapshot

        kept = snapshot()
        if kept:
            print(f"database copied to {kept}\n")

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

            # Douyin only: a profile URL is keyed on the sec_uid the
            # Douyin pages carry, and nothing reads a TikTok or
            # YouTube profile here.
            author = None
            if args.authors and args.platform.startswith("douyin"):
                from .browser import AUTHOR_URL as PROFILE_URL

                def read_profile(sec_uid: str):
                    return browser.read(PROFILE_URL.format(sec_uid=sec_uid)).fetched

                author = authors(session, read_profile)

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
                author=author,
                on_progress=show,
            )

        if author is not None and author.spent["visits"]:
            spent = author.spent
            print(
                f"\n{spent['visits']} profile(s) read for a 抖音号, "
                f"{spent['seconds'] / 60:.1f} min of this pass"
            )

        from .survival import findings, today_at_a_glance

        # This platform only, not the family. `findings` groups 图文
        # under douyin for the dashboard, which is right there -- one
        # table, one comparison. It is wrong here: a pass that checked
        # 241 videos would report the notes' removals as its own, and
        # the two runs would each claim the same comebacks.
        mine = [
            f for f in findings(session, args.platform)
            if f.platform == args.platform
        ]
        new_gone, back = today_at_a_glance(mine)

        manifest = write_manifest(session, directory, args.platform)
        print(
            f"\nread {report['read']}; saved {report['saved']} file(s) "
            f"({report['bytes'] / 1_000_000_000:.2f} GB); "
            f"{report['gone']} gone (the site served another video); "
            f"{report['unreadable']} unreadable\n"
            f"of those, {new_gone} first found gone today"
            + (f"; {back} came back today" if back else "")
            + f"\nfiles in {directory}\nmanifest {manifest}"
        )

        # The 抖音号 is a separate pass, because it is read once per
        # account rather than once per video. Separate turned out to
        # mean forgotten: it had never been run, so five hundred
        # accounts had a display name and no handle -- and a display
        # name does not find an author again, which is what the
        # interviews need. A removed post's author can delete the
        # account at any time, so this says the number out loud at
        # the end of every pass rather than waiting to be asked.
        from .fetch_authors import wanted as authors_wanted

        missing = len(authors_wanted(session))
        if missing:
            print(
                f"\n{missing} account(s) still have no 抖音号. The display "
                "name does not find an author again; the handle is only on "
                "the profile:\n  python -m app.fetch_authors --apply"
            )

        if args.report:
            # The page is a snapshot, so it is rewritten at the end of
            # a pass rather than served live: what it shows is exactly
            # what this run left behind.
            from .report import build

            args.report.write_text(build(session), encoding="utf-8")
            print(f"page {args.report}")


if __name__ == "__main__":  # pragma: no cover
    main()
