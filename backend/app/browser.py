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
#:
#: Absolute, and derived from this file rather than the working
#: directory. A relative path means `app.login` and `app.fetch_videos`
#: can sign in to and read from two different profiles depending on
#: where each was run, which looks exactly like a session that will
#: not persist.
DEFAULT_PROFILE = Path(__file__).resolve().parent.parent / ".browser-profile"

#: The site's own pages, which is what a signed-in browser can read.
#: The share host stays the fallback for an anonymous fetch.
VIDEO_URL = "https://www.douyin.com/video/{video_id}"
AUTHOR_URL = "https://www.douyin.com/user/{sec_uid}"

#: Cookies the site sets once a sign-in has actually happened. This
#: is what "signed in" is decided by -- not by reading the page.
#:
#: The first version looked for words like 扫码登录 in the rendered
#: text, which Douyin shows in its sidebar to signed-in visitors too.
#: Every page then looked like a login wall, the run asked to sign in
#: again at each one, and none of it had anything to do with whether
#: the session was there.
_SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt", "passport_csrf_token")

#: A challenge: a page asking the person to prove something. Narrow on
#: purpose, and only consulted when the session is present -- so it
#: cannot be confused with being signed out.
_CHALLENGE = ("滑动验证", "拖动滑块", "安全验证", "请完成验证", "验证码")

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
    """A signed-in Chromium, kept open across many reads.

    One tab, reused. A tab per page was slower, and opening dozens of
    them is itself the kind of traffic that gets a session challenged.
    """

    def __init__(self, context, pause_seconds: float = 2.0) -> None:
        self._context = context
        self._pause = pause_seconds
        self._read_any = False
        self._page = None

    # -- session ---------------------------------------------------

    def is_signed_in(self) -> bool:
        """Whether the site has actually set a session cookie.

        Asked of the cookie jar, not of the page. A rendered page
        mentions signing in whether or not you are.
        """
        for cookie in self._context.cookies():
            if cookie.get("name") not in _SESSION_COOKIES:
                continue
            if not (cookie.get("value") or "").strip():
                continue
            if "douyin.com" in (cookie.get("domain") or ""):
                return True
        return False

    def wait_until_signed_in(self, timeout_seconds: float = 900.0) -> bool:
        """Hold the browser open until a sign-in lands, or time runs out.

        Polled rather than waiting on a keypress. The first version
        waited for Enter and closed the browser the moment it got one
        -- including the empty line left in a paste buffer -- which
        shut the window while the code from an SMS was still being
        typed into it. Nothing the operator does in the browser can
        end this early except succeeding.
        """
        deadline = time.monotonic() + timeout_seconds
        said = 0.0
        while time.monotonic() < deadline:
            if self.is_signed_in():
                return True
            now = time.monotonic()
            if now - said > 20:
                remaining = int(deadline - now)
                print(
                    f"  still waiting for the sign-in ({remaining}s left) -- "
                    "take as long as you need",
                    flush=True,
                )
                said = now
            time.sleep(2.0)
        return self.is_signed_in()

    # -- reading ---------------------------------------------------

    def read(self, url: str, settle_seconds: float = 2.5) -> PageRead:
        """Navigate the tab, let the page render, hand back its HTML."""
        if self._read_any and self._pause:
            time.sleep(self._pause)
        self._read_any = True

        if self._page is None or self._page.is_closed():
            self._page = self._context.new_page()
        page = self._page

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
            landed = page.url
        except Exception as problem:  # noqa: BLE001 - recorded, not raised
            return PageRead(Fetched(url=url, error=type(problem).__name__))

        return PageRead(
            Fetched(url=url, html=html, http_status=status),
            wall=self._is_wall(landed, text),
        )

    def _is_wall(self, landed: str, text: str) -> bool:
        """Whether the page asked for a person instead of answering.

        Two different situations, and they are told apart by the
        cookie jar rather than by the words on the page: no session
        means signed out, and a session plus a challenge means the
        site wants this particular request proved.
        """
        if not self.is_signed_in():
            return True
        if "verify" in landed or "captcha" in landed:
            return True
        return any(marker in text for marker in _CHALLENGE)

    def wait_for_person(self, message: str, timeout_seconds: float = 900.0) -> None:
        """Stop and let the operator deal with what is on screen.

        Enter carries on, but losing the terminal does not end the
        wait: without one it polls until the session is back, because
        closing the browser mid-challenge is the one thing that must
        not happen.
        """
        print(f"\n  {message}")
        print("  Deal with it in the browser window, then press Enter here.")
        try:
            input()
            return
        except EOFError:
            print("  (no terminal to wait on -- watching the session instead)")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.is_signed_in():
                return
            time.sleep(3.0)


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
    """Whether the profile still holds a session for the site.

    A page has to have been opened first: cookies for a domain are
    only in the jar once something from it has been loaded.
    """
    return browser.is_signed_in()


def host_of(url: str) -> str:
    return urlparse(url).netloc
