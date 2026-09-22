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

#: One profile per site, so signing in to one never disturbs the
#: other -- and so a blocked or challenged session on one platform
#: costs only that platform's collection.
PROFILES: dict[str, Path] = {
    "douyin": DEFAULT_PROFILE,
    "tiktok": DEFAULT_PROFILE.with_name(".browser-profile-tiktok"),
}

#: Where the site's cookies live, for deciding whether a session is
#: actually present, and where to open to find out.
DOMAINS: dict[str, str] = {"douyin": "douyin.com", "tiktok": "tiktok.com"}
HOMES: dict[str, str] = {
    "douyin": "https://www.douyin.com/",
    "tiktok": "https://www.tiktok.com/",
}

#: The site's own pages, which is what a signed-in browser can read.
#: The share host stays the fallback for an anonymous fetch.
VIDEO_URL = "https://www.douyin.com/video/{video_id}"
AUTHOR_URL = "https://www.douyin.com/user/{sec_uid}"

#: Cookies the site sets once a sign-in has actually happened.
#:
#: Read from the jar rather than from the page. The first attempt
#: looked for words like 扫码登录 in the rendered text, which Douyin
#: shows in its sidebar to signed-in visitors too, so every page
#: looked like a login wall.
#:
#: The second attempt read the jar but included
#: `passport_csrf_token`, which the site sets for any visitor at all.
#: A profile deleted seconds earlier then reported a session, login
#: returned immediately and closed the window -- while an SMS code
#: was being typed into it. The same mistake inverted.
#:
#: So: only cookies that a sign-in creates, and nothing that merely
#: proves a page was loaded. `python -m app.login --show-cookies`
#: prints the names in a profile (never the values) when this list
#: needs checking against what the site actually sets.
_SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt", "uid_tt", "sid_guard")

#: A challenge: a page asking the person to prove something. Narrow on
#: purpose, and only consulted when the session is present -- so it
#: cannot be confused with being signed out.
_CHALLENGE = ("滑动验证", "拖动滑块", "安全验证", "请完成验证", "验证码")

#: A page that loaded but holds none of what was asked for.
_EMPTY = ("暂无", "内容不存在", "页面不存在", "该作品已下架")

#: The site's own API calls worth keeping the answer to.
#:
#: douyin.com renders the video after the document arrives: its
#: `RENDER_DATA` holds the page shell and not even the video's id, so
#: there is nothing in the HTML to parse. The record comes back in
#: one of these, and it is the same aweme record the app reads --
#: `desc`, `author`, `statistics`, `create_time` -- so capturing the
#: response beats guessing at the markup it eventually becomes.
_WANTED_RESPONSES = (
    "/aweme/detail/",
    "/aweme/v1/web/aweme/detail",
    "/user/profile/other",
    "/user/profile/self",
    "/aweme/post/",
)


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

    def __init__(
        self, context, pause_seconds: float = 2.0, domain: str = "douyin.com"
    ) -> None:
        self._context = context
        self._pause = pause_seconds
        #: Which site's cookies count as a session here. Both sites are
        #: the same company's and use the same cookie names, so without
        #: this a TikTok profile would read a Douyin session as its own.
        self._domain = domain
        self._read_any = False
        self._page = None

    # -- session ---------------------------------------------------

    def session_cookies(self) -> list[str]:
        """Names of the sign-in cookies present. Never their values."""
        found = []
        for cookie in self._context.cookies():
            name = cookie.get("name")
            if name not in _SESSION_COOKIES:
                continue
            if not (cookie.get("value") or "").strip():
                continue
            if self._domain in (cookie.get("domain") or ""):
                found.append(name)
        return found

    def cookie_names(self) -> list[tuple[str, str]]:
        """Every cookie's name and domain, for checking the list above.

        Values are never returned or printed: they are the session.
        """
        return sorted(
            {
                (cookie.get("name") or "", cookie.get("domain") or "")
                for cookie in self._context.cookies()
            }
        )

    def is_signed_in(self) -> bool:
        """Whether a sign-in has actually happened in this profile.

        Asked of the cookie jar, not of the page: a rendered page
        mentions signing in whether or not you are. And asked only of
        cookies a sign-in creates -- see [_SESSION_COOKIES] for the
        two ways this has been got wrong.
        """
        return bool(self.session_cookies())

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

        payloads: list[dict] = []

        def keep(response) -> None:
            if not any(part in response.url for part in _WANTED_RESPONSES):
                return
            try:
                payloads.append(response.json())
            except Exception:  # noqa: BLE001 - a body that is not JSON
                pass

        page.on("response", keep)
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
            # The record arrives after hydration, so give it a moment
            # more when nothing has come back yet.
            waited = 0.0
            while not payloads and waited < 8.0:
                page.wait_for_timeout(500)
                waited += 0.5
            html = page.content()
            text = page.inner_text("body")[:4000]
            landed = page.url
        except Exception as problem:  # noqa: BLE001 - recorded, not raised
            return PageRead(Fetched(url=url, error=type(problem).__name__))
        finally:
            page.remove_listener("response", keep)

        return PageRead(
            Fetched(
                url=url, html=html, http_status=status, payloads=payloads
            ),
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

    # -- fetching a file -------------------------------------------

    def download(self, url: str, referer: str | None = None, timeout_ms: int = 120_000):
        """Fetch a URL's bytes through this signed-in context.

        Not `requests`. A Douyin media URL is served to the session
        that asked for it, checked against its cookies and the page it
        came from; a bare request for the same address gets a 403 or a
        few hundred bytes of error page that would otherwise be
        written to disk as an .mp4. Going through the browser's own
        request context means the cookies, the user agent and the
        referer are the ones the site just saw.

        Returns (bytes, status) and never raises: a video that could
        not be fetched is recorded, not fatal to the run.
        """
        headers = {"referer": referer} if referer else {}
        try:
            response = self._context.request.get(
                url, headers=headers, timeout=timeout_ms
            )
            return response.body(), response.status
        except Exception as problem:  # noqa: BLE001 - reported by the caller
            return None, type(problem).__name__

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
    platform: str = "douyin",
):
    """A browser using `profile`, created on first use.

    `platform` decides the locale it presents and which site's cookies
    count as a session. A Chinese locale on tiktok.com is not wrong,
    exactly -- the record is parsed from JSON, not from the interface
    -- but it invites a different region's page for no benefit.
    """
    chinese = platform.startswith("douyin")
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
            locale="zh-CN" if chinese else "en-US",
            timezone_id="Asia/Shanghai" if chinese else "America/New_York",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield Browser(
                context,
                pause_seconds=pause_seconds,
                domain=DOMAINS.get(platform, "douyin.com"),
            )
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
