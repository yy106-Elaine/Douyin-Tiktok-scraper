"""A real browser, logged in once, reused for every page after.

Douyin's own site renders in the browser and gates a great deal
behind a session: a profile fetched without cookies is a download
prompt, and a run of requests eventually meets a verification page
instead of a video. Neither is something an HTTP client can answer.

So the fetching happens in a browser that keeps its profile on disk.
`python -m app.login` opens it once, the operator signs in by hand --
scanning a code, passing whatever check appears -- and the session
stays in that directory. Every later run reuses it and no credential
is ever read, typed or stored by this code.

**The window is visible on purpose.** A verification page is a thing
a person can answer and a script cannot, and the run pauses for that
rather than hammering past it. `--headless` exists for when a run is
known to be quiet, and it will simply record the pages it could not
read.

**Whose account this is matters.** Every request here carries the
signed-in identity, and this study is about what a platform removes
from a community it polices. A separate research account keeps the
collection off a personal one; `--profile` takes a directory, so
more than one can exist side by side.

Playwright is imported inside the functions that need it, so the
rest of the backend runs without it installed.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .douyin_page import Fetched

#: Where the signed-in session lives. Beside the database, because it
#: is the same kind of thing: local state a collection depends on and
#: which must never reach the repository.
DEFAULT_PROFILE = Path(".browser-profile")

#: The site's own pages, which is what a signed-in browser can read.
#: The share host stays the fallback for an anonymous fetch.
VIDEO_URL = "https://www.douyin.com/video/{video_id}"
AUTHOR_URL = "https://www.douyin.com/user/{sec_uid}"

#: Wording that means the page is asking the person for something
#: rather than answering. Checked against the rendered text.
_WALL = (
    "验证",
    "滑动",
    "拖动",
    "请完成",
    "登录后",
    "扫码登录",
    "手机号登录",
)

#: A page that loaded but holds none of what was asked for.
_EMPTY = ("暂无", "内容不存在", "页面不存在", "该作品已下架")


@dataclass
class PageRead:
    """A rendered page, or why there isn't one."""

    fetched: Fetched
    #: True when the page asked for a person: a login prompt or a
    #: verification challenge. Recorded rather than retried, because
    #: retrying is what turns a challenge into a block.
    wall: bool = False


class Browser:
    """A signed-in Chromium, kept open across many reads."""

    def __init__(self, context, pause_seconds: float = 2.0) -> None:
        self._context = context
        self._pause = pause_seconds
        self._read_any = False

    def read(self, url: str, settle_seconds: float = 2.5) -> PageRead:
        """Navigate, let the page render, and hand back its HTML."""
        if self._read_any and self._pause:
            time.sleep(self._pause)
        self._read_any = True

        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            status = response.status if response is not None else None
            # Douyin fills the page after the document arrives. Waiting
            # on a selector would tie this to one build's markup, so it
            # waits for the network to go quiet and then a moment more.
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            time.sleep(settle_seconds)
            html = page.content()
            text = page.inner_text("body")[:4000]
        except Exception as problem:  # noqa: BLE001 - recorded, not raised
            return PageRead(Fetched(url=url, error=type(problem).__name__))
        finally:
            page.close()

        return PageRead(
            Fetched(url=url, html=html, http_status=status),
            wall=any(marker in text for marker in _WALL),
        )

    def wait_for_person(self, message: str) -> None:
        """Stop and let the operator deal with what is on screen."""
        print(f"\n  {message}")
        print("  Deal with it in the browser window, then press Enter here.")
        try:
            input()
        except EOFError:
            # Not attached to a terminal: carry on and let the page be
            # recorded as unreadable rather than hanging forever.
            print("  (no terminal to wait on -- continuing)")


@contextmanager
def open_browser(
    profile: Path = DEFAULT_PROFILE,
    headless: bool = False,
    pause_seconds: float = 2.0,
):
    """A browser using `profile`, created on first use."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as missing:  # pragma: no cover - environment
        raise SystemExit(
            "Playwright is not installed. From backend/:\n"
            "    ./.venv/bin/pip install playwright\n"
            "    ./.venv/bin/playwright install chromium"
        ) from missing

    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield Browser(context, pause_seconds=pause_seconds)
        finally:
            context.close()


def signed_in(browser: Browser) -> bool:
    """Whether the profile's session still opens the site."""
    read = browser.read("https://www.douyin.com/", settle_seconds=3.0)
    if read.fetched.html is None:
        return False
    return not read.wall


def host_of(url: str) -> str:
    return urlparse(url).netloc
