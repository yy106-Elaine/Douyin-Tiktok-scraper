"""The takedown instrument.

These tests exist because the ways this can be wrong are all silent. A
removed video answering 200, a bot challenge read as a removal, a
removal time quoted to the minute -- each produces a plausible number
that is not a measurement.
"""
from datetime import datetime, timedelta

from app.models import LinkCheck
from app.recheck import (
    ALIVE,
    AUTHOR_GONE,
    GONE,
    UNKNOWN,
    UNREACHABLE,
    WITHHELD,
    FetchResult,
    Target,
    classify,
    collected_targets,
    due_targets,
    excerpt,
    minimum_gap,
    page_title,
    run_round,
)
from app.survival import findings, summarise

NOW = datetime(2026, 9, 17, 12, 0)


def _check(**kwargs) -> LinkCheck:
    defaults = dict(
        platform="tiktok",
        target_kind="video",
        video_id="7301234567890123456",
        url="https://www.tiktok.com/@a/video/7301234567890123456",
        checked_at=NOW,
        http_status=200,
    )
    return LinkCheck(**{**defaults, **kwargs})


def _page(body: str, status: int = 200) -> FetchResult:
    return FetchResult(status=status, final_url="https://www.tiktok.com/x", body=body)


class TestClassification:
    def test_a_normal_page_is_alive(self):
        assert classify(_check(page_title="someone on TikTok")) == ALIVE

    def test_a_removed_video_answering_200_is_not_alive(self):
        """The failure mode that would make every video look alive."""
        check = _check(
            http_status=200,
            page_title="TikTok",
            excerpt="Video currently unavailable",
        )
        assert classify(check) == GONE

    def test_a_404_is_gone_even_without_wording(self):
        assert classify(_check(http_status=404, page_title=None)) == GONE

    def test_a_network_failure_is_never_a_takedown(self):
        assert classify(_check(error="URLError", http_status=None)) == UNREACHABLE

    def test_a_rate_limit_is_not_a_takedown(self):
        assert classify(_check(http_status=429)) == UNKNOWN

    def test_a_bot_challenge_outranks_removal_wording(self):
        """A challenge means we learned nothing, whatever else is on it."""
        check = _check(
            excerpt="Verify to continue. Video currently unavailable.",
        )
        assert classify(check) == UNKNOWN

    def test_a_missing_account_outranks_the_video_page(self):
        check = _check(excerpt="Couldn't find this account")
        assert classify(check) == AUTHOR_GONE

    def test_a_private_account_is_withheld_not_gone(self):
        assert classify(_check(excerpt="This account is private")) == WITHHELD

    def test_douyin_wording_is_recognised(self):
        assert classify(_check(platform="douyin", excerpt="该作品已被删除")) == GONE
        assert classify(_check(platform="douyin", excerpt="该账号已注销")) == AUTHOR_GONE

    def test_an_unrecognised_page_is_unknown_not_alive(self):
        """A stale marker list must be loud, not quietly wrong."""
        check = _check(http_status=418, page_title="???")
        assert classify(check) == UNKNOWN

    def test_a_redirect_to_the_site_root_is_not_the_video(self):
        check = _check(http_status=200, final_url="https://www.tiktok.com/")
        assert classify(check) == WITHHELD


class TestReadingAResponse:
    def test_the_title_is_extracted_and_stripped(self):
        assert page_title("<html><head><title> Hi \n there </title>") == "Hi there"

    def test_scripts_are_not_part_of_the_excerpt(self):
        body = "<script>var x = 'Video currently unavailable'</script><p>Real text</p>"
        assert "Real text" in excerpt(body)
        assert "var x" not in excerpt(body)

    def test_the_excerpt_is_bounded(self):
        assert len(excerpt("<p>" + "a" * 5000)) <= 1200


class TestCadence:
    def test_new_videos_are_checked_more_often_than_old_ones(self):
        assert minimum_gap(timedelta(hours=3)) < minimum_gap(timedelta(days=30))

    def test_a_video_never_checked_is_always_due(self, client, api_key):
        from app.db import SessionLocal

        target = Target(
            platform="tiktok",
            video_id="7301234567890123456",
            url="https://x",
            author_handle=None,
            first_seen=NOW,
        )
        with SessionLocal() as session:
            assert due_targets(session, NOW, [target]) == [target]

    def test_a_video_checked_minutes_ago_is_not_due(self, client, api_key):
        from app.db import SessionLocal

        target = Target(
            platform="tiktok",
            video_id="7301234567890123456",
            url="https://x",
            author_handle=None,
            first_seen=NOW,
        )
        with SessionLocal() as session:
            run_round(
                session,
                fetcher=lambda url: _page("<title>fine</title>"),
                now=NOW,
                targets=[target],
                pause_seconds=0,
            )
            assert due_targets(session, NOW + timedelta(minutes=10), [target]) == []
            # And due again once the cadence has elapsed.
            assert due_targets(session, NOW + timedelta(hours=9), [target]) == [target]


class TestARound:
    def _target(self, handle="someone"):
        return Target(
            platform="tiktok",
            video_id="7301234567890123456",
            url="https://www.tiktok.com/@someone/video/7301234567890123456",
            author_handle=handle,
            first_seen=NOW - timedelta(days=1),
        )

    def test_a_check_records_what_the_server_returned(self, client):
        from sqlalchemy import select

        from app.db import SessionLocal

        with SessionLocal() as session:
            report = run_round(
                session,
                fetcher=lambda url: _page("<title>someone on TikTok</title>"),
                now=NOW,
                targets=[self._target()],
                pause_seconds=0,
            )
            assert report.verdicts == {ALIVE: 1}
            check = session.scalars(select(LinkCheck)).one()
            assert check.http_status == 200
            assert check.page_title == "someone on TikTok"
            assert check.checked_at == NOW

    def test_the_author_is_checked_only_when_the_video_is_missing(self, client):
        from sqlalchemy import select

        from app.db import SessionLocal

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=lambda url: _page("<title>fine</title>"),
                now=NOW,
                targets=[self._target()],
                pause_seconds=0,
            )
            kinds = [c.target_kind for c in session.scalars(select(LinkCheck))]
            assert kinds == ["video"]

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=lambda url: _page("Video currently unavailable"),
                now=NOW + timedelta(days=1),
                targets=[self._target()],
                pause_seconds=0,
            )
            kinds = {c.target_kind for c in session.scalars(select(LinkCheck))}
            assert kinds == {"video", "author"}


class TestFindings:
    def _run(self, session, body, when, handle="someone"):
        run_round(
            session,
            fetcher=lambda url: _page(body),
            now=when,
            targets=[
                Target(
                    platform="tiktok",
                    video_id="7301234567890123456",
                    url="https://www.tiktok.com/@someone/video/7301234567890123456",
                    author_handle=handle,
                    first_seen=NOW,
                )
            ],
            pause_seconds=0,
        )

    def test_removal_is_reported_as_an_interval_not_a_moment(self, client):
        """The schedule's precision must not be presented as the platform's."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._run(session, "<title>fine</title>", NOW)
            self._run(session, "Video currently unavailable", NOW + timedelta(days=2))

            finding = findings(session, "tiktok")[0]
            assert finding.is_gone
            assert finding.last_alive_at == NOW
            assert finding.first_gone_at == NOW + timedelta(days=2)
            assert finding.uncertainty == timedelta(days=2)

            lower, upper = finding.lifetime()
            assert lower < upper  # a bracket, never one number

    def test_a_video_that_comes_back_resets_the_span(self, client):
        """Reinstatement is a finding, not noise to smooth over."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            self._run(session, "<title>fine</title>", NOW)
            self._run(session, "Video currently unavailable", NOW + timedelta(days=1))
            self._run(session, "<title>fine again</title>", NOW + timedelta(days=2))

            finding = findings(session, "tiktok")[0]
            assert not finding.is_gone
            assert finding.last_alive_at == NOW + timedelta(days=2)

    def test_unreachable_checks_are_excluded_from_the_rate(self, client):
        """An unreachable video is not evidence of survival or removal."""
        from app.db import SessionLocal

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=lambda url: FetchResult(error="URLError"),
                now=NOW,
                targets=[
                    Target(
                        platform="tiktok",
                        video_id="7301234567890123456",
                        url="https://x",
                        author_handle=None,
                        first_seen=NOW,
                    )
                ],
                pause_seconds=0,
            )
            summary = summarise(findings(session, "tiktok"))
            assert summary.tracked == 1
            assert summary.gone == 0
            assert summary.alive == 0
            assert summary.unmeasured == 1
            assert summary.rate is None  # not 0%, which would be a claim

    def test_a_banned_account_is_named_as_the_outcome(self, client):
        """Whole-account loss is a different event from one video pulled."""
        from app.db import SessionLocal

        def fetcher(url):
            if "/video/" in url:
                return _page("Video currently unavailable")
            return _page("Couldn't find this account")

        with SessionLocal() as session:
            run_round(
                session,
                fetcher=fetcher,
                now=NOW,
                targets=[
                    Target(
                        platform="tiktok",
                        video_id="7301234567890123456",
                        url="https://www.tiktok.com/@someone/video/7301234567890123456",
                        author_handle="someone",
                        first_seen=NOW,
                    )
                ],
                pause_seconds=0,
            )
            assert findings(session, "tiktok")[0].outcome == AUTHOR_GONE


def test_collected_targets_include_posts_and_unpaired_links(client, api_key):
    from app.db import SessionLocal

    client.post(
        "/api/links/shared",
        json={
            "raw_text": "https://www.tiktok.com/@a/video/7301234567890123456",
            "shared_at": "2026-09-14T12:00:00Z",
        },
        headers={"X-API-Key": api_key},
    )
    with SessionLocal() as session:
        ids = {target.video_id for target in collected_targets(session)}
        assert ids == {"7301234567890123456"}


def test_the_findings_page_renders_and_states_its_limits(client, api_key):
    body = client.get("/dashboard/takedowns?key=test-admin-key&platform=tiktok").text
    assert "Takedown findings" in body
    assert "One vantage point" in body       # the geo caveat is on the page
    assert "Not measured is not alive" in body
    assert "app.recheck" in body


def test_the_findings_page_needs_the_admin_key(client):
    assert client.get("/dashboard/takedowns").status_code == 401


def test_only_in_scope_videos_are_tracked(client, api_key):
    """1,072 of 1,126 YouTube rows were excluded, and all were tracked.

    The cost of re-checking them daily is the smaller half. A takedown
    rate computed over adult nappies, a children's cartoon and a shelf
    of Japanese vlogs is a rate for those, and the page presented it
    as the corpus's.
    """
    from app.db import SessionLocal
    from app.recheck import collected_targets
    from app import youtube

    def caller(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": v}} for v in ("keep", "drop")]}
        titles = {
            "keep": "我们是拉拉 女朋友日常",
            # A daily poster of adult nappies. 拉拉裤 is not the topic.
            "drop": "#卧床老人 #护理用品 #成人拉拉裤",
        }
        return {
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "channelId": "UC1",
                        "channelTitle": "c",
                        "title": titles[video_id],
                        "description": "",
                        "publishedAt": "2026-09-16T08:30:00Z",
                    },
                    "statistics": {},
                    "status": {"privacyStatus": "public"},
                }
                for video_id in params["id"].split(",")
            ]
        }

    with SessionLocal() as session:
        youtube.collect(session, ["拉拉"], caller=caller)
        tracked = {target.video_id for target in collected_targets(session)}

    assert "keep" in tracked
    assert "drop" not in tracked


def test_the_two_strata_get_their_own_rate(client, api_key):
    """A 百合短剧 channel and a person posting their own life.

    Both are in the corpus. Neither explains the other: one posts
    episodes on a schedule and has no author to interview about a
    takedown. Pooling them produces a number that describes neither
    population, and that number is what gets quoted.
    """
    from app import youtube
    from app.db import SessionLocal
    from app.views import fiction_ids

    titles = {
        "own": "我和女朋友的日常 #拉拉 #女同",
        "drama": "【GL Anime】《盼你归来》EP03 #百合短剧 #双女主",
    }

    def caller(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": v}} for v in titles]}
        return {
            "items": [
                {
                    "id": video_id,
                    "snippet": {
                        "channelId": "UC1",
                        "channelTitle": "c",
                        "title": titles[video_id],
                        "description": "",
                        "publishedAt": "2026-09-16T08:30:00Z",
                    },
                    "statistics": {},
                    "status": {"privacyStatus": "public"},
                }
                for video_id in params["id"].split(",")
            ]
        }

    with SessionLocal() as session:
        youtube.collect(session, ["拉拉"], caller=caller)
        assert fiction_ids(session, "youtube") == {"drama"}

    body = client.get("/dashboard/takedowns?key=test-admin-key&platform=youtube").text
    assert "Rate — firsthand" in body
    assert "Rate — scripted drama" in body

    listing = client.get(
        "/dashboard?key=test-admin-key&platform=youtube&show=fiction only"
    ).text
    assert "盼你归来" in listing
    assert "我和女朋友的日常" not in listing


def test_youtube_is_always_due(client):
    """A YouTube check is fifty ids per request, for one quota unit.

    The cadence exists to stop a page-by-page fetch hammering a site.
    Where a check is nearly free it buys nothing and costs the only
    thing this table is for: a removal is dated to the gap between
    the check that found it alive and the one that found it gone.
    """
    from datetime import timedelta

    from app.recheck import minimum_gap

    assert minimum_gap(timedelta(hours=1), "youtube") == timedelta(0)
    # The page platforms keep it.
    assert minimum_gap(timedelta(hours=1), "douyin") == timedelta(hours=8)
    assert minimum_gap(timedelta(days=30), "douyin") == timedelta(days=6)
    assert minimum_gap(timedelta(days=200), "douyin") == timedelta(days=27)


def test_a_youtube_video_checked_an_hour_ago_is_due_again(client):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import LinkCheck
    from app.recheck import Target, due_targets

    first_seen = datetime(2026, 9, 21, 9, 0)
    target = Target(
        platform="youtube",
        video_id="abc123",
        url="https://www.youtube.com/watch?v=abc123",
        author_handle=None,
        first_seen=first_seen,
    )

    with SessionLocal() as session:
        session.add(
            LinkCheck(
                platform="youtube",
                video_id="abc123",
                url=target.url,
                checked_at=first_seen,
                http_status=200,
            )
        )
        session.commit()

        due = due_targets(
            session, now=first_seen + timedelta(hours=1), targets=[target]
        )

    assert [item.video_id for item in due] == ["abc123"]
