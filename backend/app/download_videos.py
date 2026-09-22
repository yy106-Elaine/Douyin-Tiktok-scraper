"""Keep a copy of each collected video's file, before it is gone.

    ./.venv/bin/python -m app.download_videos            # what is missing
    ./.venv/bin/python -m app.download_videos --apply    # go and get it

The re-check tells you *that* a video disappeared. It cannot tell you
anything about what disappeared: not the footage, not the frames, not
what was said in it. Every question of the form "what kind of video
gets removed" needs the video, and once a takedown has happened there
is nothing left to answer it with -- the metadata survives, the
subject of the study does not.

So the copy is made early. Of one evening's 73 Douyin videos, 8 were
already gone within hours of being posted; those eight can never be
analysed now, and that is the whole argument for running this on the
same day as the collection rather than at the end.

How it works: the same signed-in browser the rest of the pipeline
uses opens the video's page, Douyin's own API answer is captured, and
the file addresses inside it are fetched *through the browser's
request context* -- with its cookies, its user agent and the page it
came from as the referer. A plain HTTP request for the same address
is answered with a few hundred bytes of error page, which is exactly
the kind of thing that gets written to disk as an .mp4 and only
noticed months later, so every download is checked for an MP4 header
before it is kept.

The file goes on disk, not in the database; the row records where it
went, how big it was and its SHA-256. The digest is what makes a
later claim checkable -- the copy analysed is provably the copy
downloaded, which matters most for the videos whose originals can no
longer be compared against.
"""
from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .browser import VIDEO_URL as BROWSER_VIDEO_URL, DEFAULT_PROFILE, open_browser
from .clock import now as utc_now
from .douyin_page import file_urls
from .models import WebVideo

#: Seconds between videos. Same reasoning as everywhere else here: a
#: run that gets itself blocked has lost observations it cannot go
#: back for. Larger than the metadata passes because these are
#: multi-megabyte fetches.
PAUSE_SECONDS = 3.0

#: Where the copies go by default. Deliberately outside the
#: repository: this is other people's video, it is not ours to
#: publish, and a folder inside a git checkout is one `git add -A`
#: away from being pushed.
DEFAULT_DIR = Path.home() / "Documents" / "douyin-videos"

#: Below this, whatever came back is not a video. An error page, a
#: redirect stub and a truncated response all land here.
MIN_BYTES = 50_000


def looks_like_video(blob: bytes) -> bool:
    """Whether these bytes are actually a video file.

    Checked because the failure this guards against is silent. A
    media URL fetched without the right session answers 200 with a
    JSON error or an HTML page, and saving that as `<id>.mp4` gives a
    folder that looks complete and a corpus that is not -- discovered,
    otherwise, at the point of analysis, when the video is gone.

    An MP4 declares itself in the second box of the file; the other
    two forms are what Douyin has actually served in place of one.
    """
    if len(blob) < MIN_BYTES:
        return False
    if blob[4:8] == b"ftyp":
        return True
    # Fragmented or unusual muxes: accept a recognisable container
    # signature anywhere in the first kilobyte rather than insisting
    # on the exact offset.
    head = blob[:1024]
    return b"ftyp" in head or head.startswith(b"\x1aE\xdf\xa3")  # mp4 / webm


def wanted(session: Session, redownload: bool = False) -> list[WebVideo]:
    """Videos whose page we have read and whose file we do not hold.

    A row whose file is recorded but missing from disk comes back:
    the folder is allowed to move or be cleaned out, and the fix is
    to run this again rather than to repair the database by hand.
    """
    rows = session.scalars(
        select(WebVideo).where(WebVideo.error.is_(None)).order_by(WebVideo.video_id)
    ).all()
    if redownload:
        return list(rows)
    return [row for row in rows if not held(row)]


def held(row: WebVideo) -> bool:
    """Whether this row's file is on disk now, not merely recorded."""
    if not row.local_path:
        return False
    path = Path(row.local_path)
    return path.is_file() and path.stat().st_size >= MIN_BYTES


def record(session: Session, row: WebVideo, path: Path | None, blob: bytes | None,
           error: str | None) -> None:
    if blob is not None and path is not None:
        row.local_path = str(path)
        row.file_bytes = len(blob)
        row.file_sha256 = hashlib.sha256(blob).hexdigest()
        row.downloaded_at = utc_now()
        row.download_error = None
    else:
        row.download_error = error
    session.commit()


def save(directory: Path, video_id: str, blob: bytes) -> Path:
    """Write the file, via a temporary name.

    An interrupted run must not leave a half-written .mp4 that the
    next run reads as "already have it".
    """
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{video_id}.mp4"
    partial = directory / f"{video_id}.mp4.part"
    partial.write_bytes(blob)
    partial.replace(final)
    return final


def fetch_one(browser, video_id: str) -> tuple[bytes | None, str | None]:
    """The video's bytes, or why there are none.

    The id is checked before anything is downloaded. Douyin answers a
    request for a removed video by serving the next recommended one,
    and the addresses in that answer are the replacement's -- so
    without this the folder would quietly fill with other people's
    videos filed under the ids of the removed ones, which is worse
    than a gap.
    """
    page_url = BROWSER_VIDEO_URL.format(video_id=video_id)
    read = browser.read(page_url)
    if read.wall:
        return None, "wall"
    if read.fetched.error:
        return None, read.fetched.error

    urls = file_urls(read.fetched.payloads, video_id=video_id)
    if not urls:
        return None, "no file address for this id"

    last = "no url answered"
    for url in urls:
        blob, status = browser.download(url, referer=page_url)
        if blob is None:
            last = str(status)
            continue
        if not looks_like_video(blob):
            last = f"not a video ({len(blob)} bytes, http {status})"
            continue
        return blob, None
    return None, last


def run(
    session: Session,
    rows: list[WebVideo],
    directory: Path,
    browser,
    pause_seconds: float = PAUSE_SECONDS,
    on_progress=None,
) -> dict[str, int]:
    report = {"saved": 0, "failed": 0, "bytes": 0}
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        if index > 1 and pause_seconds:
            time.sleep(pause_seconds)

        blob, error = fetch_one(browser, row.video_id)
        if blob is None:
            record(session, row, None, None, error)
            report["failed"] += 1
            outcome = f"-- {error}"
        else:
            path = save(directory, row.video_id, blob)
            record(session, row, path, blob, None)
            report["saved"] += 1
            report["bytes"] += len(blob)
            outcome = f"{len(blob) / 1_000_000:.1f} MB"

        if on_progress:
            on_progress(index, total, f"{row.video_id} {outcome}")
    return report


def write_manifest(session: Session, directory: Path) -> Path:
    """A CSV beside the files, so the folder is readable on its own.

    The database is the record; this is for looking at the folder in
    Finder, and for handing the set to a tool that does not know
    about the database.
    """
    import csv

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.csv"
    rows = session.scalars(
        select(WebVideo)
        .where(WebVideo.local_path.isnot(None))
        .order_by(WebVideo.posted_on)
    ).all()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["video_id", "file", "bytes", "sha256", "posted_on",
             "author_name", "author_handle", "caption", "video_url"]
        )
        for row in rows:
            writer.writerow([
                row.video_id,
                Path(row.local_path).name if row.local_path else "",
                row.file_bytes or "",
                row.file_sha256 or "",
                row.posted_on.isoformat() if row.posted_on else "",
                row.author_name or "",
                row.author_handle or "",
                (row.caption or "").replace("\n", " "),
                BROWSER_VIDEO_URL.format(video_id=row.video_id),
            ])
    return path


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(
        description="Download a copy of each collected Douyin video."
    )
    parser.add_argument("--apply", action="store_true", help="actually download")
    parser.add_argument("--limit", type=int, default=None, help="stop after N videos")
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_DIR, help=f"where to put them (default {DEFAULT_DIR})"
    )
    parser.add_argument("--pause", type=float, default=PAUSE_SECONDS)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--redownload",
        action="store_true",
        help="fetch again even where a file is already held",
    )
    parser.add_argument(
        "--skip-gone",
        action="store_true",
        help=(
            "leave out videos already found removed -- they cannot be "
            "downloaded, and the site answers with a different video"
        ),
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        rows = wanted(session, redownload=args.redownload)

        if args.skip_gone:
            from .recheck import disappeared

            gone = disappeared(session)
            before = len(rows)
            rows = [row for row in rows if row.video_id not in gone]
            if before != len(rows):
                print(f"skipping {before - len(rows)} already found gone")

        if args.limit is not None:
            rows = rows[: args.limit]

        if not rows:
            print("nothing to download. Run app.fetch_videos first if this is zero.")
            write_manifest(session, args.dir)
            return

        if not args.apply:
            print(
                f"{len(rows):,} video(s) to download into {args.dir}.\n"
                "Add --apply to fetch them."
            )
            return

        def show(done: int, total: int, outcome: str) -> None:
            print(f"[{done}/{total}] {outcome}", flush=True)

        with open_browser(
            profile=args.profile, headless=args.headless, pause_seconds=0
        ) as browser:
            if not browser.is_signed_in():
                raise SystemExit(
                    "Not signed in. Run: ./.venv/bin/python -m app.login"
                )
            report = run(
                session,
                rows,
                args.dir,
                browser,
                pause_seconds=args.pause,
                on_progress=show,
            )

        manifest = write_manifest(session, args.dir)
        print(
            f"\nsaved {report['saved']} "
            f"({report['bytes'] / 1_000_000_000:.2f} GB), {report['failed']} failed\n"
            f"files in {args.dir}\nmanifest {manifest}"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
