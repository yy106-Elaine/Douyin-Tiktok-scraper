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
