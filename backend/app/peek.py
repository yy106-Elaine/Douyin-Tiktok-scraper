"""Look at what the browser actually got for one page.

    ./.venv/bin/python -m app.peek 7686722818378549115

For the pages that open perfectly in a person's browser and come back
empty here. Three explanations were argued for those -- a rate limit,
the wrong kind of URL, the blocked media -- and the first two were
wrong when tested and the third when tried. This stops arguing and
writes the page out.

Prints what arrived and saves the HTML, so the next question is about
a file rather than about a theory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .browser import HOMES, PROFILES, open_browser
from .fetch_videos import SITES


def main() -> None:  # pragma: no cover - a looking tool
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="+")
    parser.add_argument("--platform", default="douyin", choices=sorted(SITES))
    parser.add_argument("--heavy", action="store_true",
                        help="let the page fetch the video and the pictures")
    parser.add_argument("--dir", type=Path, default=Path("peeked"))
    args = parser.parse_args()

    site = SITES[args.platform]
    args.dir.mkdir(parents=True, exist_ok=True)

    with open_browser(
        PROFILES[args.platform], headless=False, pause_seconds=0,
        platform=args.platform, light=not args.heavy,
    ) as browser:
        browser.read(HOMES[args.platform], settle_seconds=1.0)
        print(f"signed in: {browser.is_signed_in()}")
        for video_id in args.video_id:
            url = site.page_url(video_id, None)
            seen = browser.read(url)
            page = seen.fetched
            html = page.html or ""
            facts = site.facts(html, page.payloads)
            print(f"\n{url}")
            print(f"  http {page.http_status}  error={page.error}  "
                  f"wall={seen.wall}")
            print(f"  html {len(html):,} chars, {len(page.payloads)} payload(s)")
            for key in ("og:title", "og:description", "description"):
                mark = f'property="{key}"'
                print(f"  meta {key}: {'present' if mark in html or key in html else 'ABSENT'}")
            for marker in ("验证", "滑动", "登录", "打开抖音", "下载"):
                if marker in html:
                    print(f"  html mentions {marker!r}")
            print(f"  parsed: {facts}")
            where = args.dir / f"{video_id}.html"
            where.write_text(html, encoding="utf-8")
            if page.payloads:
                (args.dir / f"{video_id}.json").write_text(
                    json.dumps(page.payloads, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            print(f"  written to {where}")


if __name__ == "__main__":  # pragma: no cover
    main()
