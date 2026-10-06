"""A challenge nobody answers must not cost the whole night.

The wall prompt used to block on `input()`. A run started in the
evening to work through the night stopped at the first challenge and
was still sitting at the prompt in the morning, having read nothing
for eight hours.
"""
import time

from app.browser import Browser


class _NoSession:
    """A cookie jar with no sign-in in it, so the wall never clears."""

    def cookies(self):
        return []


def _browser() -> Browser:
    made = Browser.__new__(Browser)
    made._context = _NoSession()
    made._pause = 0
    made._domain = "douyin.com"
    made._read_any = False
    made._page = None
    made._stopped_waiting = False
    return made


def test_the_wait_ends_by_itself_and_the_run_carries_on():
    browser = _browser()
    started = time.monotonic()

    answered = browser.wait_for_person("a wall", timeout_seconds=1.0)

    assert answered is False
    assert time.monotonic() - started < 5.0


def test_it_waits_once_and_not_once_per_page():
    """Fifteen minutes a video is the same lost night by instalments."""
    browser = _browser()
    browser.wait_for_person("a wall", timeout_seconds=1.0)

    started = time.monotonic()
    answered = browser.wait_for_person("the same wall", timeout_seconds=60.0)

    assert answered is False
    assert time.monotonic() - started < 1.0


def test_a_session_that_comes_back_ends_the_wait_at_once():
    class _SignsIn:
        def __init__(self):
            self.asked = 0

        def cookies(self):
            self.asked += 1
            if self.asked > 1:
                # A value, because a named cookie with an empty one is
                # not a session -- see `session_cookies`.
                return [{
                    "name": "sessionid",
                    "value": "x",
                    "domain": ".douyin.com",
                }]
            return []

    browser = _browser()
    browser._context = _SignsIn()

    assert browser.wait_for_person("a wall", timeout_seconds=30.0) is True


def test_a_challenge_is_not_cleared_by_the_session_being_present():
    """The wall wait was resolving itself in three seconds, by itself.

    `_is_wall` reports two different things: signed out, and signed in
    but challenged. For the second the cookies are there the whole
    time, so "the session is back" was true on the first poll and
    nobody had done anything -- twenty-two of them in one night, each
    followed by reads of a page that was still asking.
    """
    class _HasSession:
        def cookies(self):
            return [{"name": "sessionid", "value": "x", "domain": ".douyin.com"}]

    browser = _browser()
    browser._context = _HasSession()
    started = time.monotonic()

    answered = browser.wait_for_person("a challenge", timeout_seconds=1.0)

    assert answered is False
    # It waited out its timeout rather than declaring itself resolved.
    assert time.monotonic() - started >= 1.0


def test_signing_in_during_the_wait_still_ends_it():
    """The case the check was written for, which must keep working."""
    class _SignsIn:
        def __init__(self):
            self.asked = 0

        def cookies(self):
            self.asked += 1
            if self.asked > 1:
                return [{
                    "name": "sessionid", "value": "x", "domain": ".douyin.com",
                }]
            return []

    browser = _browser()
    browser._context = _SignsIn()

    assert browser.wait_for_person("signed out", timeout_seconds=30.0) is True
