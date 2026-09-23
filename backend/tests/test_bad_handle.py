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


def test_a_round_says_what_it_is_doing(db):
    """Ten minutes of silence is indistinguishable from a hang.

    A full daily sweep is a few hundred pages two seconds apart. It
    printed nothing until the end, and someone watching a still
    terminal reasonably concludes it has died and kills the round
    halfway through -- losing the half it had not reached, on a day
    whose observations cannot be gone back for.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import SharedLink
    from app.recheck import FetchResult, run_round

    with SessionLocal() as session:
        for n in range(3):
            session.add(SharedLink(
                participant_id="p1",
                platform="douyin",
                raw_text=f"#lwl https://v.douyin.com/a{n}/",
                video_id=f"768677373298808281{n}",
                canonical_url=f"https://www.douyin.com/video/768677373298808281{n}",
                shared_at=datetime(2026, 9, 21 + n, 10, 0),
            ))
        session.commit()

        seen = []
        run_round(
            session,
            fetcher=lambda url: FetchResult(status=200, final_url=url, body="<html></html>"),
            pause_seconds=0,
            ignore_cadence=True,
            on_progress=lambda done, total, what: seen.append((done, total)),
        )

    assert [done for done, _ in seen] == [1, 2, 3]
    assert {total for _, total in seen} == {3}
