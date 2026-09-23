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

    TikTok rows, because Douyin is not checked from here at all --
    see BROWSER_ONLY.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import SharedLink
    from app.recheck import FetchResult, run_round

    with SessionLocal() as session:
        for n in range(3):
            session.add(SharedLink(
                participant_id="p1",
                platform="tiktok",
                raw_text=f"#wlw #chinese https://vm.tiktok.com/a{n}/",
                video_id=f"768677373298808281{n}",
                canonical_url=f"https://www.tiktok.com/@a/video/768677373298808281{n}",
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


def test_douyin_is_left_to_the_command_that_can_read_it(db):
    """202 Douyin checks, 202 of them UNKNOWN, every one HTTP 200.

    douyin.com answers a request with no session with a JavaScript
    shell. Grading that UNKNOWN is right -- a download wall was being
    read as "alive" -- but a check certain to be UNKNOWN before it is
    made should not be made: `survival.summarise` flags a video as
    doubtful once over half its checks are uninformative, so a daily
    sweep would within days mark every Douyin video doubtful, on noise
    this study generated itself.

    They are named in the report, not dropped quietly, and the report
    says which command does check them.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import SharedLink
    from app.recheck import FetchResult, run_round

    with SessionLocal() as session:
        session.add(SharedLink(
            participant_id="p1",
            platform="douyin",
            raw_text="#lwl https://v.douyin.com/aaa/",
            video_id="7686773732988082810",
            canonical_url="https://www.douyin.com/video/7686773732988082810",
            shared_at=datetime(2026, 9, 21, 10, 0),
        ))
        session.commit()

        asked = []
        report = run_round(
            session,
            fetcher=lambda url: asked.append(url) or FetchResult(status=200, body=""),
            pause_seconds=0,
            ignore_cadence=True,
        )

    assert asked == []
    assert report.checked == 0
    assert report.needs_browser == 1
    assert "app.fetch_videos --platform douyin --refresh" in str(report)


def test_a_blind_request_does_not_make_a_video_doubtful(db):
    """All 177 Douyin videos read "mostly uninformative" at once.

    A sweep by a fetcher that cannot read douyin.com wrote 202
    checks, every one HTTP 200 with nothing in it, and `summarise`
    called every video doubtful -- including ones whose removal the
    browser pass had confirmed. That is the right warning about a
    flaky site and the wrong one about a fetcher pointed at the wrong
    door.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import ID_CONFIRMED
    from app.survival import findings, summarise

    with SessionLocal() as session:
        # One real observation, from the browser pass.
        session.add(LinkCheck(
            platform="douyin",
            video_id="7686773732988082810",
            target_kind="video",
            url="https://www.douyin.com/video/7686773732988082810",
            http_status=200,
            evidence=ID_CONFIRMED,
            checked_at=datetime(2026, 9, 22, 10, 58),
        ))
        # Three shells from the anonymous sweep.
        for hour in range(3):
            session.add(LinkCheck(
                platform="douyin",
                video_id="7686773732988082810",
                target_kind="video",
                url="https://www.douyin.com/video/7686773732988082810",
                http_status=200,
                checked_at=datetime(2026, 9, 23, 10 + hour),
            ))
        session.commit()

        found = findings(session, "douyin")
        assert len(found) == 1
        assert found[0].blind == 3
        assert (found[0].checks, found[0].uninformative) == (1, 0)
        assert summarise(found).doubtful == 0
        assert summarise(found).alive == 1


def test_a_douyin_check_that_did_read_something_still_counts(db):
    """Identified by construction, not by platform.

    A 404, a removal notice or a verified id read from douyin.com is
    an observation and counts for everything.
    """
    from datetime import datetime

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.survival import findings

    with SessionLocal() as session:
        session.add(LinkCheck(
            platform="douyin",
            video_id="7686773732988082811",
            target_kind="video",
            url="https://www.douyin.com/video/7686773732988082811",
            http_status=404,
            checked_at=datetime(2026, 9, 23, 11),
        ))
        session.commit()
        found = findings(session, "douyin")
        assert found[0].blind == 0
        assert found[0].checks == 1
