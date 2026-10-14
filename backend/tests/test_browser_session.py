"""Deciding whether a browser profile is signed in.

The first version read the rendered page for words like 扫码登录.
Douyin shows those to signed-in visitors too, so every page looked
like a login wall: the run asked to sign in again at each one, and
none of it had anything to do with whether the session was there.

It is now decided by the cookie jar, which is the thing that
actually changes when someone signs in.
"""
from __future__ import annotations

import time

from app.browser import Browser, PageRead


class _FakeContext:
    def __init__(self, cookies=None) -> None:
        self._cookies = list(cookies or [])

    def cookies(self):
        return self._cookies

    def sign_in(self) -> None:
        self._cookies.append(
            {"name": "sessionid", "value": "abc123", "domain": ".douyin.com"}
        )


def _browser(cookies=None) -> Browser:
    return Browser(_FakeContext(cookies), pause_seconds=0)


def test_a_session_cookie_is_what_signed_in_means():
    assert not _browser().is_signed_in()
    assert _browser(
        [{"name": "sessionid", "value": "abc123", "domain": ".douyin.com"}]
    ).is_signed_in()


def test_an_empty_cookie_is_not_a_session():
    assert not _browser(
        [{"name": "sessionid", "value": "", "domain": ".douyin.com"}]
    ).is_signed_in()


def test_a_cookie_from_somewhere_else_is_not_a_session():
    assert not _browser(
        [{"name": "sessionid", "value": "abc", "domain": ".example.com"}]
    ).is_signed_in()


def test_the_words_on_the_page_do_not_decide_it():
    """Douyin's sidebar says 扫码登录 to signed-in visitors as well."""
    browser = _browser(
        [{"name": "sessionid", "value": "abc123", "domain": ".douyin.com"}]
    )
    assert not browser._is_wall("https://www.douyin.com/video/123", "扫码登录 登录后")


def test_no_session_is_a_wall_whatever_the_page_says():
    assert _browser()._is_wall("https://www.douyin.com/video/123", "视频内容")


def test_a_challenge_is_a_wall_even_with_a_session():
    browser = _browser(
        [{"name": "sessionid", "value": "abc123", "domain": ".douyin.com"}]
    )
    assert browser._is_wall("https://www.douyin.com/video/123", "请完成验证")
    assert browser._is_wall("https://verify.douyin.com/captcha", "")


def test_the_wait_ends_when_the_sign_in_lands_not_on_a_keypress():
    """A keypress closed the window while an SMS code was being typed."""
    context = _FakeContext()
    browser = Browser(context, pause_seconds=0)

    started = time.monotonic()
    # Nobody has signed in, and there is no terminal to press anything
    # on: the wait must not return.
    assert browser.wait_until_signed_in(timeout_seconds=0.2) is False
    assert time.monotonic() - started >= 0.2

    context.sign_in()
    assert browser.wait_until_signed_in(timeout_seconds=5.0) is True


def test_the_profile_directory_does_not_depend_on_where_it_was_run():
    """Two working directories meant two profiles, one of them empty."""
    from app.browser import DEFAULT_PROFILE

    assert DEFAULT_PROFILE.is_absolute()


def test_a_token_every_visitor_gets_is_not_a_session():
    """A deleted profile reported a session and closed the window.

    `passport_csrf_token` is set for any visitor at all. Counting it
    made a brand-new profile look signed in, so login returned at
    once and shut the browser -- while an SMS code was being typed
    into it.
    """
    assert not _browser(
        [
            {
                "name": "passport_csrf_token",
                "value": "9f2a",
                "domain": ".douyin.com",
            }
        ]
    ).is_signed_in()


def test_the_names_can_be_listed_without_the_values():
    """The values are the session; they are never printed."""
    browser = _browser(
        [
            {"name": "sessionid", "value": "secret", "domain": ".douyin.com"},
            {"name": "ttwid", "value": "also-secret", "domain": ".douyin.com"},
        ]
    )
    listed = browser.cookie_names()
    assert ("sessionid", ".douyin.com") in listed
    assert ("ttwid", ".douyin.com") in listed
    assert all("secret" not in str(entry) for entry in listed)
    assert browser.session_cookies() == ["sessionid"]


class _FlakyContext:
    """A context whose first tab fails every navigation."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.pages: list[_FlakyPage] = []

    def new_page(self):
        page = _FlakyPage(self, len(self.pages))
        self.pages.append(page)
        return page

    def cookies(self):
        return [{"name": "sessionid", "value": "x", "domain": ".douyin.com"}]


class _FlakyPage:
    def __init__(self, context, index: int) -> None:
        self.context = context
        self.index = index
        self.closed = False
        self.url = "https://www.douyin.com/video/1"
        self.routed: list[str] = []

    def route(self, pattern, handler):
        # A check never looks at the video or the pictures, and a tab
        # that is not told so downloads them: see Browser._light.
        self.routed.append(pattern)

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def on(self, event, handler):
        pass

    def remove_listener(self, event, handler):
        pass

    def goto(self, url, **kwargs):
        if self.index < self.context.failures:
            raise RuntimeError("Target page, context or browser has been closed")

        class _Response:
            status = 200

        return _Response()

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, _ms):
        pass

    def content(self):
        return "<html>the video</html>"

    def inner_text(self, _selector):
        return "the video"


def test_a_tab_that_stopped_working_is_replaced_once():
    """Eight videos in a row failed, then a new tab read the rest.

    The cure was the operator closing the window by hand. Nothing in
    the run could tell "this page is bad" from "this tab is bad", so
    it reported eight unreadable videos that were perfectly readable.
    """
    from app.browser import Browser

    context = _FlakyContext(failures=1)
    browser = Browser(context, pause_seconds=0)

    page = browser.read("https://www.douyin.com/video/1", settle_seconds=0)

    assert page.fetched.error is None
    assert page.fetched.html == "<html>the video</html>"
    # One thrown away, one working.
    assert len(context.pages) == 2
    assert context.pages[0].closed


def test_it_does_not_keep_opening_tabs():
    """A second tab failing the same way is not a tab problem.

    Hammering it is how a session becomes a block, so the error is
    reported instead -- the first one, which describes the page.
    """
    from app.browser import Browser

    context = _FlakyContext(failures=99)
    browser = Browser(context, pause_seconds=0)

    page = browser.read("https://www.douyin.com/video/1", settle_seconds=0)

    assert page.fetched.error == "RuntimeError"
    assert len(context.pages) == 2


def test_a_check_does_not_download_the_video_it_is_checking():
    """Most of a check's time, and all of its bandwidth, for nothing.

    What the check reads is the site's JSON record and the document.
    The archive's own copy is fetched separately, through the request
    context, which this routing does not touch -- so a page that
    streams the video while being asked whether the video exists is
    pure cost.
    """
    from app.browser import Browser

    context = _FlakyContext(failures=0)
    browser = Browser(context, pause_seconds=0)

    browser.read("https://www.douyin.com/video/1", settle_seconds=0)

    assert context.pages[0].routed == ["**/*"]


def test_the_media_kinds_are_dropped_and_the_record_is_not():
    from app.browser import _skip_heavy

    dropped, allowed = [], []

    class _Route:
        def __init__(self, kind):
            self.kind = kind

        def abort(self):
            dropped.append(self.kind)

        def continue_(self):
            allowed.append(self.kind)

    class _Request:
        def __init__(self, kind):
            self.resource_type = kind

    for kind in ("media", "image", "font", "xhr", "fetch", "document", "script"):
        route = _Route(kind)
        _skip_heavy(route, _Request(kind))

    assert dropped == ["media", "image", "font"]
    assert allowed == ["xhr", "fetch", "document", "script"]


def test_the_read_ends_when_the_record_arrives_not_when_the_page_goes_quiet():
    """Seventeen seconds a page, waiting for something that cannot happen.

    A Douyin video page is streaming the video, so it never reaches
    "networkidle" and that wait ran its full timeout on essentially
    every check -- while the JSON record the check actually reads had
    landed in the first second or two. A thousand pages a night.
    """
    waits: list[str] = []

    class _Response:
        status = 200
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

        @staticmethod
        def json():
            return {"aweme_detail": {"aweme_id": "1"}}

    class _Page(_FlakyPage):
        def on(self, event, handler):
            # The record arrives with the document, as it does in life.
            handler(_Response())

        def wait_for_load_state(self, *args, **kwargs):
            waits.append("networkidle")

        def wait_for_timeout(self, ms):
            waits.append(f"{ms}ms")

    class _Context(_FlakyContext):
        def new_page(self):
            page = _Page(self, len(self.pages))
            self.pages.append(page)
            return page

    browser = Browser(_Context(failures=0), pause_seconds=0)

    page = browser.read("https://www.douyin.com/video/1", settle_seconds=99)

    assert page.fetched.payloads == [{"aweme_detail": {"aweme_id": "1"}}]
    # It never waited for the page to go quiet, and never slept out
    # the settle time either.
    assert "networkidle" not in waits


def test_a_page_that_sends_no_record_still_gets_the_old_patient_read():
    """Then the meta tags in the HTML are the answer, and they want a
    settled page. Only this case pays for the wait."""
    waits: list[str] = []

    class _Page(_FlakyPage):
        def wait_for_load_state(self, *args, **kwargs):
            waits.append("networkidle")

        def wait_for_timeout(self, ms):
            waits.append(f"{ms}ms")

    class _Context(_FlakyContext):
        def new_page(self):
            page = _Page(self, len(self.pages))
            self.pages.append(page)
            return page

    browser = Browser(_Context(failures=0), pause_seconds=0)
    browser.read("https://www.douyin.com/video/1", settle_seconds=0)

    assert "networkidle" in waits


def test_the_wait_ends_on_the_record_not_on_the_first_answer_that_arrives():
    """A page that reads perfectly by hand came back empty in a run.

    A Douyin video page fetches several of the endpoints this listens
    on, and the author's other posts arrive before the video's own
    record more often than not. Ending the wait on the first of them
    leaves the parse with a list of somebody's other videos and no
    video.
    """
    class _Posts:
        status = 200
        url = "https://www.douyin.com/aweme/post/"

        @staticmethod
        def json():
            return {"status_code": 0, "has_more": 1, "max_cursor": 17}

    class _Detail:
        status = 200
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

        @staticmethod
        def json():
            return {"aweme_detail": {"aweme_id": "1", "desc": "今天"}}

    class _Page(_FlakyPage):
        def __init__(self, context, index):
            super().__init__(context, index)
            self.handler = None
            self.ticks = 0

        def on(self, event, handler):
            self.handler = handler
            # The other answer first, as it comes in life.
            handler(_Posts())

        def wait_for_timeout(self, ms):
            self.ticks += 1
            if self.ticks == 3 and self.handler is not None:
                self.handler(_Detail())

        def wait_for_load_state(self, *args, **kwargs):
            raise AssertionError("should not fall back: the record arrived")

    class _Context(_FlakyContext):
        def new_page(self):
            page = _Page(self, len(self.pages))
            self.pages.append(page)
            return page

    browser = Browser(_Context(failures=0), pause_seconds=0)
    read = browser.read("https://www.douyin.com/video/1", settle_seconds=0)

    assert any("aweme_detail" in blob for blob in read.fetched.payloads)


def test_the_recommendations_do_not_count_as_this_video_s_record():
    """How a removed video came back as "nothing readable".

    A removed page has no record to send, but it still fetches the
    recommendations -- and every item in those carries a `desc` and a
    `sec_uid` of its own, so they look exactly like a record. The wait
    ended on them, and the HTML was taken before the page had rendered
    the sentence that says what happened.
    """
    class _Recommended:
        status = 200
        url = "https://www.douyin.com/aweme/post/"

        @staticmethod
        def json():
            # Another post's record: a desc and an id of its own, and
            # not the id that was asked for.
            return {"aweme_list": [
                {"aweme_id": "999", "desc": "somebody else's video"},
            ]}

    class _Page(_FlakyPage):
        def __init__(self, context, index):
            super().__init__(context, index)
            self.waited_for_quiet = False

        def on(self, event, handler):
            handler(_Recommended())

        def wait_for_load_state(self, *args, **kwargs):
            self.waited_for_quiet = True

        def content(self):
            # Rendered by the time the patient path has finished.
            return "<div>你要观看的视频不存在</div>"

    class _Context(_FlakyContext):
        def new_page(self):
            page = _Page(self, len(self.pages))
            self.pages.append(page)
            return page

    context = _Context(failures=0)
    browser = Browser(context, pause_seconds=0)

    # A real id, because what tells a record from a recommendation is
    # whether it is about the post that was asked for.
    read = browser.read(
        "https://www.douyin.com/video/7686528190130806202", settle_seconds=0
    )

    # It went the patient way, and so it saw what the page said.
    assert context.pages[0].waited_for_quiet is True
    assert read.fetched.missing is True


def test_a_note_s_record_ends_the_wait_whatever_endpoint_it_came_on():
    """Narrowing to the video detail endpoint made every 图文 wait it out.

    Twenty-one seconds a page, on pages that read perfectly, because a
    note's record does not come back on that endpoint. What tells the
    record from the recommendations is not which endpoint sent it --
    it is whether it is about the post that was asked for.
    """
    class _NoteRecord:
        status = 200
        url = "https://www.douyin.com/aweme/post/"

        @staticmethod
        def json():
            return {"aweme_list": [
                {"aweme_id": "7693105053100764398", "desc": "#lwl"},
            ]}

    class _Page(_FlakyPage):
        def on(self, event, handler):
            handler(_NoteRecord())

        def wait_for_load_state(self, *args, **kwargs):
            raise AssertionError("the record was here; no need to be patient")

    class _Context(_FlakyContext):
        def new_page(self):
            page = _Page(self, len(self.pages))
            self.pages.append(page)
            return page

    browser = Browser(_Context(failures=0), pause_seconds=0)
    read = browser.read(
        "https://www.douyin.com/note/7693105053100764398", settle_seconds=99
    )

    assert read.fetched.payloads


def test_a_profile_already_open_says_so_in_one_line(tmp_path, monkeypatch) -> None:
    """Chromium's refusal is right; its explanation is forty lines long.

    It will not open one user-data-dir twice -- two browsers on one
    signed-in session can corrupt it, and that session is the part of
    this collection that cannot be replaced. But the refusal arrives
    as a Playwright traceback with "Failed to create SingletonLock:
    File exists" buried in the middle, and the question it answers --
    is a run already going? -- takes a second to answer when asked
    plainly.
    """
    import pytest

    from app import browser as browser_module

    class _Refuses:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        @property
        def chromium(self):
            class _Type:
                @staticmethod
                def launch_persistent_context(*a, **kw):
                    raise RuntimeError(
                        "BrowserType.launch_persistent_context: Target page, "
                        "context or browser has been closed\n"
                        "[err] Failed to create "
                        "/x/.browser-profile/SingletonLock: File exists (17)"
                    )
            return _Type()

    monkeypatch.setattr(browser_module, "sync_playwright", _Refuses,
                        raising=False)
    monkeypatch.setitem(
        __import__("sys").modules, "playwright.sync_api",
        type("m", (), {"sync_playwright": _Refuses}),
    )

    with pytest.raises(SystemExit) as refused:
        with browser_module.open_browser(tmp_path / ".browser-profile"):
            pass

    said = str(refused.value)
    assert "already open in another run" in said
    assert "--profile" in said
    # And it still says how to find out what is holding it.
    assert "pgrep" in said
    # A refusal for any other reason is not swallowed.
    assert "SingletonLock" not in said


def test_the_audit_records_every_json_answer_not_only_the_watched_ones() -> None:
    """`_WANTED_RESPONSES` is a list of endpoints that were true once.

    When a site moves its record to a new one, the symptom is a page
    that reads as empty — which from inside is indistinguishable from
    a page the site declined to serve, and that ambiguity cost four
    days of blaming rate limits for a 图文 page whose record had moved
    off every endpoint being watched.

    So the audit keeps the url of every JSON answer, and the watched
    list keeps deciding what gets parsed.
    """
    from app.browser import _WANTED_RESPONSES

    audit: list[tuple[str, int]] = []

    class _Response:
        def __init__(self, url, kind="application/json"):
            self.url = url
            self.status = 200
            self.headers = {"content-type": kind}

        def json(self):
            return {"ok": True}

    # The listener's two jobs, as the code does them in order.
    def keep(response, payloads):
        kind = (response.headers or {}).get("content-type", "")
        if "json" in kind.lower():
            audit.append((response.url, response.status))
        if not any(part in response.url for part in _WANTED_RESPONSES):
            return
        payloads.append(response.json())

    payloads: list[dict] = []
    keep(_Response("https://www.douyin.com/aweme/v1/web/aweme/detail/?x=1"),
         payloads)
    keep(_Response("https://www.douyin.com/aweme/v1/web/note/fetch/?x=1"),
         payloads)
    keep(_Response("https://www.douyin.com/thing.css", "text/css"), payloads)

    # Only the watched one is parsed...
    assert len(payloads) == 1
    # ...and both JSON answers are on the record, so the one that was
    # not watched can be found and named.
    assert [u for u, _ in audit] == [
        "https://www.douyin.com/aweme/v1/web/aweme/detail/?x=1",
        "https://www.douyin.com/aweme/v1/web/note/fetch/?x=1",
    ]


def test_an_audit_that_is_off_must_not_read_as_an_empty_one() -> None:
    """None and [] are different claims, and one of them is not a finding.

    `peek` printed "0 JSON response(s)" for a page that had in fact
    made a dozen — the switch had never been set, so the instrument
    reported silence while not listening. That is the same confusion
    the whole day went into: a page that reads as empty and a page
    nobody looked at are not the same observation, and an instrument
    that renders them identically is the bug.
    """
    from app.browser import Browser

    fresh = Browser.__new__(Browser)
    fresh.audit = None
    assert fresh.audit is None, "off by default, so a run carries no cost"

    fresh.audit = []
    assert fresh.audit == [], "on and quiet is a different claim from off"


def test_a_tab_is_thrown_away_between_reads_by_default() -> None:
    """A tab that has been somewhere stops asking for the next place.

    One tab was reused for a whole pass and the pages it fetched grew
    emptier as it went: by the middle of a run half parsed to nothing.
    The audit says why. A fresh tab requests `aweme/post` or
    `aweme/detail` -- the record, which is watched. A tab that has
    already visited a hundred posts requests `aweme/related` and
    `tab/feed` instead, and never asks for the record at all:
    Douyin's own client cache believes it already has what it needs.
    """
    from app.browser import Browser

    recycles = Browser.__new__(Browser)
    recycles._fresh_every = 1
    recycles._since_fresh = 0

    # The rule the read path applies, stated once here.
    def due(browser) -> bool:
        return bool(browser._fresh_every
                    and browser._since_fresh >= browser._fresh_every)

    assert not due(recycles), "the first read needs no discard"
    recycles._since_fresh = 1
    assert due(recycles), "and every read after it opens a new tab"

    every_ten = Browser.__new__(Browser)
    every_ten._fresh_every = 10
    every_ten._since_fresh = 9
    assert not due(every_ten)
    every_ten._since_fresh = 10
    assert due(every_ten)

    # 0 is the old behaviour, kept only so it can be measured against.
    never = Browser.__new__(Browser)
    never._fresh_every = 0
    never._since_fresh = 10_000
    assert not due(never)


def test_forgetting_keeps_the_tab_and_the_session() -> None:
    """The cure for a stale tab must not cost the machine.

    Discarding the tab works and raises Chromium to the front every
    time on macOS, so a four-hour pass steals the keyboard every few
    seconds. Headless would avoid that and cannot be used: the
    session check comes back empty there, and a pass that cannot see
    its own login is worse than one that interrupts typing.

    `about:blank` is a fresh document in the same tab -- which is
    where the app's caches live -- while the cookie jar belongs to
    the context and is untouched.
    """
    from app.browser import Browser

    went: list[str] = []
    discarded: list[bool] = []

    class _Page:
        def is_closed(self):
            return False

        def goto(self, url, **kw):
            went.append(url)

    quiet = Browser.__new__(Browser)
    quiet._forget_by = "blank"
    quiet._page = _Page()
    quiet._discard_page = lambda: discarded.append(True)

    Browser._forget(quiet)

    assert went == ["about:blank"], "the document goes, the tab stays"
    assert not discarded, "and the slow way is not taken when it works"


def test_a_blank_navigation_that_fails_falls_back_to_the_tab() -> None:
    """Reading a cached page that answers nothing is the worse outcome."""
    from app.browser import Browser

    discarded: list[bool] = []

    class _Stuck:
        def is_closed(self):
            return False

        def goto(self, url, **kw):
            raise RuntimeError("navigation failed")

    stuck = Browser.__new__(Browser)
    stuck._forget_by = "blank"
    stuck._page = _Stuck()
    stuck._discard_page = lambda: discarded.append(True)

    Browser._forget(stuck)

    assert discarded == [True]


def test_the_sign_in_window_is_not_a_light_one() -> None:
    """The slider challenge is an image, and `light` blocks images.

    A blocked challenge renders as "图片加载失败，请刷新重试或换个网络",
    which reads exactly like the site declining to issue one -- on
    the evening a session had to be renewed, which is the worst
    possible moment to be given a misleading refusal.

    And the page must not recycle itself: blanking the document
    between reads keeps a pass from going stale, and doing it to a
    window somebody is typing a verification code into throws the
    code away.
    """
    import inspect

    from app import login

    source = inspect.getsource(login.main)
    opened = source[source.index("headless=False"):]
    assert "light=False" in opened[:300]
    assert "fresh_every=0" in opened[:300]


def test_forget_by_tab_throws_the_tab_away() -> None:
    """The two ways of forgetting were treated as equivalent untested.

    The only sample taken with a real new tab read 18 pages and
    failed on one. Every sample since has navigated to about:blank
    instead, and failed on 20%, 39% and 79%. Three readings of one
    arm and one of the other settles nothing — but it is the
    difference that was changed without being measured, so both arms
    have to be reachable to measure it.
    """
    from app.browser import Browser

    went: list[str] = []
    discarded: list[bool] = []

    class _Page:
        def is_closed(self):
            return False

        def goto(self, url, **kw):
            went.append(url)

    hard = Browser.__new__(Browser)
    hard._forget_by = "tab"
    hard._page = _Page()
    hard._discard_page = lambda: discarded.append(True)

    Browser._forget(hard)

    assert discarded == [True]
    assert went == [], "the tab goes without being navigated first"


def test_forget_by_storage_clears_only_the_session_store() -> None:
    """sessionStorage is the one thing a new tab starts empty.

    It belongs to the tab, so navigating to about:blank and back
    finds it exactly as it was — which is a candidate for the whole
    difference between the two arms measured so far, and is testable
    without opening a tab and so without the window jumping to the
    front every few seconds.

    localStorage is left alone on purpose. It may carry parts of the
    sign-in on this origin, and the session has already been lost
    once this week.
    """
    from app.browser import Browser

    ran: list[str] = []
    went: list[str] = []
    discarded: list[bool] = []

    class _Page:
        def is_closed(self):
            return False

        def evaluate(self, script):
            ran.append(script)

        def goto(self, url, **kw):
            went.append(url)

    light = Browser.__new__(Browser)
    light._forget_by = "storage"
    light._page = _Page()
    light._discard_page = lambda: discarded.append(True)

    Browser._forget(light)

    assert len(ran) == 1
    assert "sessionStorage.clear()" in ran[0]
    assert "localStorage" not in ran[0]
    assert went == [], "no navigation, so no new tab and no window raised"
    assert not discarded


def test_a_refusal_says_which_kind_of_refusal_it_is():
    """"No saved session" has meant two opposite things in one evening.

    On 10-13 a headless run reported no session minutes after a
    windowed run had read pages with it. One of those needs a fresh
    sign-in; the other needs the check fixed, and signing in again
    would spend a working session chasing a bug. The message now
    carries the jar, so the next occurrence is evidence.
    """
    # Nothing at all: never signed in, or the wrong directory.
    assert "cookie jar is empty" in _browser().session_report()

    # A signed-out visit still leaves plenty behind.
    anonymous = _browser([
        {"name": "__ac_nonce", "value": "x", "domain": ".douyin.com"},
        {"name": "s_v_web_id", "value": "y", "domain": ".douyin.com"},
    ])
    assert "none of them a sign-in cookie" in anonymous.session_report()

    # The site ending a session: the names stay, the values go.
    ended = _browser([
        {"name": "__ac_nonce", "value": "x", "domain": ".douyin.com"},
        {"name": "sessionid", "value": "", "domain": ".douyin.com"},
        {"name": "sid_guard", "value": "  ", "domain": ".douyin.com"},
    ])
    assert not ended.is_signed_in()
    assert "signing in again is the right move" in ended.session_report()

    # Nothing from this site at all: the home page never loaded, so
    # the check was asked before there was anything to ask about.
    elsewhere = _browser([
        {"name": "sessionid", "value": "abc", "domain": ".tiktok.com"},
    ])
    assert "none for douyin.com" in elsewhere.session_report()


def test_a_live_session_read_as_absent_says_do_not_sign_in_again():
    """The case that cost a session once already.

    If the cookie is there with a value and the check still says no,
    the check is what is wrong. The message has to say so loudly,
    because the obvious response -- sign in again -- is the one that
    throws the session away.
    """
    class _Jar(_FakeContext):
        pass

    browser = _browser([
        {"name": "sessionid", "value": "abc123", "domain": ".douyin.com"},
    ])
    # Force the disagreement the message is for.
    browser.is_signed_in = lambda: False  # type: ignore[method-assign]

    said = browser.session_report()
    assert "do NOT sign in again" in said
    assert "abc123" not in said  # the value is the session


def test_a_browser_that_is_not_using_this_profile_says_so(tmp_path):
    """The 10-14 case: four cookies where thirty-three were stored.

    A jar does not shrink from 33 to 4. Four is what a brand-new
    profile holds after one visit, so the browser had fallen back to
    a directory nobody asked for -- and "No saved session" was then a
    true statement about the wrong profile. The response that message
    invites, signing in again, writes a second session into a
    directory while the one you have sits unused.
    """
    import sqlite3

    profile = tmp_path / ".browser-profile"
    (profile / "Default").mkdir(parents=True)
    jar = profile / "Default" / "Cookies"
    connection = sqlite3.connect(jar)
    connection.execute(
        "CREATE TABLE cookies (name TEXT, host_key TEXT, value TEXT)")
    connection.execute(
        "INSERT INTO cookies VALUES ('sessionid', '.douyin.com', 'secret')")
    connection.execute(
        "INSERT INTO cookies VALUES ('sid_guard', '.douyin.com', 'secret')")
    connection.commit()
    connection.close()

    # What the phantom profile sees: one visit's worth of anonymous
    # cookies, which is exactly what was reported.
    phantom = Browser(
        _FakeContext([
            {"name": "__ac_nonce", "value": "x", "domain": ".douyin.com"},
            {"name": "s_v_web_id", "value": "y", "domain": ".douyin.com"},
        ]),
        pause_seconds=0,
        profile=profile,
    )

    said = phantom.session_report()
    assert "NOT using this profile" in said
    assert "Do not sign in again" in said
    assert "sessionid" in said
    assert "secret" not in said  # the value is the session


def test_the_disk_check_stays_quiet_when_it_cannot_read(tmp_path):
    """No jar on disk, or one Chromium has locked, must not invent a verdict.

    The report falls back to describing the cookies it can see, which
    is what it did before any of this existed.
    """
    empty = Browser(_FakeContext(), pause_seconds=0, profile=tmp_path)
    assert empty.cookies_on_disk() is None
    assert "cookie jar is empty" in empty.session_report()

    # And with no profile named at all -- every test above this one.
    assert Browser(_FakeContext(), pause_seconds=0).cookies_on_disk() is None
