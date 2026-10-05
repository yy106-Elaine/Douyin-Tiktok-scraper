"""Where a check's twenty seconds actually go.

    ./.venv/bin/python -m app.measure --limit 10

Two rounds of guessing at this bought 5% between them -- blocking the
video and the pictures helped, the layout pass did not -- which is
what guessing is worth. This reads a few pages with a stopwatch on
each stage and prints the medians, so the next change is aimed at
the stage that is actually expensive.

It makes ordinary checks: the same URLs the daily pass reads, with
the same session. Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from .browser import HOMES, PROFILES, open_browser
from .fetch_videos import SITES, handles, wanted

#: Named so the table reads as a sentence about where the time went.
STAGES = ("goto", "record", "quiet", "html", "total")


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def main() -> None:  # pragma: no cover - a measuring tool
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin", choices=sorted(SITES))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--heavy", action="store_true",
        help="let the page fetch the video and the pictures, as it used to",
    )
    args = parser.parse_args()

    site = SITES[args.platform]
    init_db()
    with SessionLocal() as session:
        targets = wanted(session, args.platform, refresh=True)[: args.limit]
        handle_for = handles(session, args.platform)
    if not targets:
        print("nothing to read")
        return

    timings: dict[str, list[float]] = {stage: [] for stage in STAGES}
    with open_browser(
        PROFILES[args.platform], headless=args.headless, pause_seconds=0,
        platform=args.platform, light=not args.heavy,
    ) as browser:
        browser.read(HOMES[args.platform], settle_seconds=1.0)
        for index, video_id in enumerate(targets, start=1):
            url = site.page_url(video_id, handle_for.get(video_id))
            started = time.monotonic()
            browser.read(url)
            total = time.monotonic() - started
            marks = dict(browser.last_timing)
            marks["total"] = total
            for stage in STAGES:
                timings[stage].append(marks.get(stage, 0.0))
            print(
                f"[{index}/{len(targets)}] "
                + "  ".join(f"{stage} {marks.get(stage, 0.0):5.1f}s"
                            for stage in STAGES),
                flush=True,
            )

    print("\nmedian seconds per page")
    for stage in STAGES:
        print(f"  {stage:8} {_median(timings[stage]):5.1f}")
    print(
        "\n  goto   : the document, which is one request and the ones it\n"
        "           blocks. Network and the site's own speed.\n"
        "  record : waiting for the JSON the check reads, after the\n"
        "           document arrived. The page's scripts running.\n"
        "  quiet  : the fallback wait, only for a page that sent no\n"
        "           record at all. Should be zero on most pages.\n"
        "  html   : serialising the DOM out of the browser."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
