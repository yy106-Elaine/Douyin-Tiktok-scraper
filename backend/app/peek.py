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

from .browser import (
    HOMES,
    PROFILES,
    _WANTED_RESPONSES,
    open_browser,
)
from .fetch_videos import SITES


def main() -> None:  # pragma: no cover - a looking tool
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="+")
    parser.add_argument("--platform", default="douyin", choices=sorted(SITES))
    parser.add_argument("--heavy", action="store_true",
                        help="let the page fetch the video and the pictures")
    parser.add_argument("--dir", type=Path, default=Path("peeked"))
    parser.add_argument("--profile", type=Path, default=None,
                        help="browser profile directory; defaults to this "
                             "platform's own. A run already holds that one, "
                             "so pass a copy to look while one is going")
    args = parser.parse_args()

    site = SITES[args.platform]
    args.dir.mkdir(parents=True, exist_ok=True)

    with open_browser(
        args.profile or PROFILES[args.platform],
        headless=False, pause_seconds=0,
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

            # What the page actually asked for. When the record is
            # missing, the question stops being "why did parsing
            # fail" and becomes "which of these was it supposed to be
            # in" -- and that cannot be answered without the list.
            # `_WANTED_RESPONSES` is a set of endpoints that were true
            # on the day it was written; a site that moves its record
            # to a new one produces a page that reads as empty, which
            # from inside is indistinguishable from a page the site
            # declined to serve.
            seen = browser.audit or []
            watched = [
                (u, code) for u, code in seen
                if any(part in u for part in _WANTED_RESPONSES)
            ]
            others = [row for row in seen if row not in watched]
            print(f"  {len(seen)} JSON response(s), {len(watched)} watched")
            for who, rows in (("watched", watched), ("not watched", others)):
                for u, code in rows[:12]:
                    print(f"    [{who}] {code} {u.split('?')[0]}")
            browser.audit = []


if __name__ == "__main__":  # pragma: no cover
    main()
