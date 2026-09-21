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
