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
