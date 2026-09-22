"""One malformed row must not end a round of checking."""

import http.client

from app.recheck import author_url, fetch


def test_a_display_name_is_not_an_account_address():
    """`▓ Lwl . ▓` was pasted into a URL path.

    A Douyin 抖音号 and a TikTok handle are both ASCII. A display
    name is not, and guessing that one is an address would read
    "account gone" off somebody else's page -- the difference
    between one video pulled and a whole account removed, which is
    the distinction the author check exists to make.
    """
    assert author_url("douyin", "  Lwl . ") is None
    assert author_url("douyin", "珩舟") is None
    assert author_url("tiktok", "two words") is None
    assert author_url("douyin", "") is None
    assert author_url("douyin", None) is None


def test_a_real_identifier_still_resolves():
    assert author_url("douyin", "91085508859").endswith("/user/91085508859")
    assert author_url("tiktok", "@rulebreaker2424").endswith("/@rulebreaker2424")
    assert author_url("douyin", "lwl_6.6").endswith("/user/lwl_6.6")


def test_an_invalid_url_is_an_unreadable_check_not_a_crash():
    """InvalidURL is neither URLError, OSError nor ValueError.

    It was uncaught, so it ended the process rather than the video:
    every remaining check that day simply did not happen.
    """
    result = fetch("https://www.douyin.com/user/  Lwl . ")
    assert result.error == "InvalidURL"
    assert result.status is None
    assert issubclass(http.client.InvalidURL, Exception)
