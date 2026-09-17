"""YouTube, which is a different instrument from the other two.

Nothing is read off a screen, so nothing is lossy: the id is given, the
publication time is exact, and the counts are integers. These tests
pin that difference, because the value of the platform here is that it
does not carry the phone path's uncertainties -- and quietly labelling
its data the same way would throw that away.
"""
from datetime import datetime, timedelta

import pytest

from app import youtube
from app.db import SessionLocal
from app.links import canonical_url_for
from app.models import YouTubePost
from app.parsers import youtube as parser
from app.recheck import GONE, WITHHELD, Target, check_youtube, classify, run_round
from app.survival import findings
from app.views import publication

NOW = datetime(2026, 9, 17, 12, 0)


def _item(video_id="abc123", published="2026-09-16T08:30:00Z", privacy="public"):
    return {
        "id": video_id,
        "snippet": {
            "channelId": f"UC{video_id}",
            "channelTitle": "A Channel",
            "title": "a title",
            "description": "a description",
            "publishedAt": published,
        },
        "statistics": {"viewCount": "12345", "likeCount": "678", "commentCount": "9"},
        "status": {"privacyStatus": privacy},
    }


def _caller(ids=("v1", "v2"), **kwargs):
    """A stand-in API that only knows about `ids`.

    Details are filtered against that set, not echoed back, because the
    behaviour being tested is exactly that: an id the API no longer
    returns is a video that no longer exists.
    """
    known = set(ids)

    def call(endpoint, params):
        if endpoint == "search":
            return {"items": [{"id": {"videoId": video_id}} for video_id in ids]}
        asked = params["id"].split(",")
        return {
            "items": [_item(v, **kwargs) for v in asked if v in known]
        }

    return call


class TestStructuring:
    def test_the_publication_time_is_taken_exactly(self):
        row = parser.structure(youtube.to_payload(_item()))
        assert row["posted_on"] == datetime(2026, 9, 16, 8, 30)

    def test_counts_are_not_marked_approximate(self):
        """They are integers from an API, not a rendered "12.3万"."""
        row = parser.structure(youtube.to_payload(_item()))
        assert row["counts_approximate"] is False
        assert row["like_count"] == 678
        assert row["comment_count"] == 9
        assert row["share_count"] == 12345  # views, in the spare column

    def test_the_video_id_is_present_from_the_start(self):
        row = parser.structure(youtube.to_payload(_item("xyz")))
        assert row["video_id"] == "xyz"

    def test_the_handle_falls_back_to_the_channel_id(self):
        """Either one finds the channel again, which is the point."""
        row = parser.structure(youtube.to_payload(_item("xyz")))
        assert row["author_handle"] == "UCxyz"

        payload = youtube.to_payload(_item("xyz"))
        payload["channel_handle"] = "@someone"
        assert parser.structure(payload)["author_handle"] == "someone"

    def test_a_malformed_timestamp_yields_nothing_not_a_guess(self):
        row = parser.structure(youtube.to_payload(_item(published="soon")))
        assert row["posted_on"] is None

    def test_the_exact_time_is_labelled_api_not_screen(self):
        """Mislabelling it would understate it as badly as the reverse."""
        _, _, source = publication(None, datetime(2026, 9, 16, 8, 30), None, "youtube")
        assert source == "api"


class TestSearching:
    def test_results_are_ordered_by_date_not_relevance(self):
        """Relevance ranking would bias which videos in the window got in."""
        seen = {}

        def call(endpoint, params):
            seen.update(params)
            return {"items": []}

        youtube.search_ids("拉拉", NOW - timedelta(hours=24), caller=call)
        assert seen["order"] == "date"
        assert seen["publishedAfter"] == "2026-09-16T12:00:00Z"

    def test_the_spend_is_reported(self):
        """The quota is the real constraint, so a run must say what it cost."""
        spend = youtube.Spend()
        youtube.search_ids("x", NOW, caller=_caller(), spend=spend)
        youtube.details(["v1"], caller=_caller(), spend=spend)
        assert spend.units == 101  # a search costs 100, a details call 1
        assert "search x1" in str(spend)

    def test_details_are_fetched_fifty_at_a_time(self):
        batches = []

        def call(endpoint, params):
            batches.append(params["id"].split(","))
            return {"items": [_item(v) for v in params["id"].split(",")]}

        ids = [f"v{n}" for n in range(120)]
        assert len(youtube.details(ids, caller=call)) == 120
        assert [len(batch) for batch in batches] == [50, 50, 20]


class TestCollecting:
    def test_a_run_stores_rows_and_says_what_it_did(self, client):
        with SessionLocal() as session:
            report = youtube.collect(
                session, ["拉拉"], hours=24, caller=_caller(), now=NOW
            )
            assert (report.found, report.stored) == (2, 2)

            from sqlalchemy import select

            posts = session.scalars(select(YouTubePost)).all()
            assert {post.video_id for post in posts} == {"v1", "v2"}
            assert posts[0].video_url == "https://www.youtube.com/watch?v=v1"
            assert posts[0].feed == "search:拉拉"

    def test_running_twice_in_a_day_does_not_double_count(self, client):
        """Keyword searches overlap, so this happens on every real run."""
        with SessionLocal() as session:
            youtube.collect(session, ["a"], caller=_caller(), now=NOW)
            second = youtube.collect(session, ["b"], caller=_caller(), now=NOW)
            assert second.stored == 0
            assert second.duplicates == 2

    def test_the_search_language_defaults_to_chinese(self, client):
        """Configured, not typed daily -- and it changes the sample."""
        seen = {}

        def call(endpoint, params):
            if endpoint == "search":
                seen.update(params)
                return {"items": []}
            return {"items": []}

        with SessionLocal() as session:
            youtube.collect(session, ["拉拉"], caller=call, now=NOW)
        assert seen["relevanceLanguage"] == "zh-Hans"

    def test_an_explicit_empty_language_searches_without_one(self, client):
        """So the default can be turned off, not just changed."""
        seen = {}

        def call(endpoint, params):
            if endpoint == "search":
                seen.update(params)
            return {"items": []}

        with SessionLocal() as session:
            youtube.collect(
                session, ["拉拉"], caller=call, now=NOW, relevance_language=""
            )
        assert "relevanceLanguage" not in seen

    def test_the_sampling_parameters_are_stored_on_the_row(self, client):
        """Change them mid-study and the data has to show where."""
        import json

        from sqlalchemy import select

        from app.models import CaptureEvent

        with SessionLocal() as session:
            youtube.collect(
                session, ["a"], caller=_caller(), now=NOW, region_code="TW"
            )
            payload = json.loads(
                session.scalars(select(CaptureEvent)).first().payload
            )
            assert payload["relevance_language"] == "zh-Hans"
            assert payload["region_code"] == "TW"

    def test_a_video_matching_two_keywords_is_one_observation(self, client):
        with SessionLocal() as session:
            report = youtube.collect(
                session, ["a", "b", "c"], caller=_caller(), now=NOW
            )
            assert report.keywords == 3
            assert report.found == 2  # not 6

    def test_every_matching_keyword_is_recorded_not_just_the_first(self, client):
        """Otherwise a per-keyword count depends on the list's order.

        The real lists overlap heavily -- "女同" is inside "女同性恋"
        -- so whichever came first would absorb the other's videos.
        """
        from sqlalchemy import select

        with SessionLocal() as session:
            youtube.collect(
                session, ["女同性恋", "拉拉", "女同"], caller=_caller(), now=NOW
            )
            feeds = {post.feed for post in session.scalars(select(YouTubePost))}
            assert feeds == {"search:女同性恋,拉拉,女同"}


class TestReChecking:
    def _target(self, video_id):
        return Target(
            platform="youtube",
            video_id=video_id,
            url=youtube.watch_url(video_id),
            author_handle="UCx",
            first_seen=NOW,
        )

    def test_an_id_the_api_omits_is_gone(self):
        """The whole HTML class of error disappears: there is no page."""
        results = check_youtube(
            [self._target("v1"), self._target("missing")],
            caller=_caller(ids=("v1",)),
        )
        assert results["v1"].status == 200
        assert results["missing"].status == 404

    def test_a_private_video_is_withheld_not_gone(self):
        results = check_youtube([self._target("v1")], caller=_caller(privacy="private"))
        from app.models import LinkCheck
        from app.recheck import excerpt, page_title

        check = LinkCheck(
            platform="youtube",
            url="u",
            checked_at=NOW,
            http_status=results["v1"].status,
            final_url=results["v1"].final_url,
            page_title=page_title(results["v1"].body),
            excerpt=excerpt(results["v1"].body),
        )
        assert classify(check) == WITHHELD

    def test_a_round_records_the_api_answer_as_a_check(self, client):
        with SessionLocal() as session:
            youtube.collect(session, ["a"], caller=_caller(), now=NOW)

            def checker(targets):
                return check_youtube(targets, caller=_caller(ids=("v1",)))

            run_round(session, now=NOW, pause_seconds=0, youtube_checker=checker)

            outcomes = {f.video_id: f.current for f in findings(session, "youtube")}
            assert outcomes["v2"] == GONE   # the API stopped returning it
            assert outcomes["v1"] != GONE

    def test_the_author_page_is_not_fetched_for_youtube(self, client):
        """The id lookup already answered; a channel page adds nothing."""
        from sqlalchemy import select

        from app.models import LinkCheck

        with SessionLocal() as session:
            youtube.collect(session, ["a"], caller=_caller(), now=NOW)
            run_round(
                session,
                now=NOW,
                pause_seconds=0,
                youtube_checker=lambda targets: check_youtube(
                    targets, caller=_caller(ids=())
                ),
            )
            kinds = {c.target_kind for c in session.scalars(select(LinkCheck))}
            assert kinds == {"video"}


def test_the_canonical_url_is_a_watch_url():
    assert canonical_url_for("youtube", "abc") == "https://www.youtube.com/watch?v=abc"


def test_a_missing_api_key_is_explained_not_a_stack_trace(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(youtube.YouTubeError) as raised:
        youtube.api_key()
    assert "YOUTUBE_API_KEY" in str(raised.value)


def test_keywords_can_come_from_a_file(tmp_path):
    path = tmp_path / "keywords.txt"
    path.write_text("拉拉\n# a comment\n\nles\n", encoding="utf-8")
    assert youtube.read_keywords(None, str(path)) == ["拉拉", "les"]
    assert youtube.read_keywords("a, b", None) == ["a", "b"]


def test_youtube_appears_as_its_own_tab(client):
    body = client.get("/dashboard?key=test-admin-key&platform=youtube").text
    assert "Videos &mdash; youtube" in body or "Videos — youtube" in body


def test_the_overview_shows_every_platform(client, api_key):
    body = client.get("/dashboard/overview?key=test-admin-key").text
    assert "Overview" in body
    for platform in ("douyin", "tiktok", "youtube"):
        assert platform in body
    # Colour never carries the state on its own.
    assert "still up" in body and "disappeared" in body and "not measured" in body


def test_the_overview_needs_the_admin_key(client):
    assert client.get("/dashboard/overview").status_code == 401


def test_the_overview_keeps_a_way_out_to_each_platform(client):
    """Hiding the platform row there stranded the page."""
    body = client.get("/dashboard/overview?key=test-admin-key").text
    for platform in ("douyin", "tiktok", "youtube"):
        assert f'href="/dashboard?platform={platform}' in body


def test_youtube_publication_time_reaches_the_findings_page(client):
    """Its ids carry no timestamp, so it has to come from the row.

    Without this the Published and Lifetime columns -- the study's
    actual measure -- were empty for every YouTube video.
    """
    from app.recheck import FetchResult, run_round

    with SessionLocal() as session:
        youtube.collect(session, ["a"], caller=_caller(), now=NOW)
        run_round(
            session,
            now=NOW,
            pause_seconds=0,
            youtube_checker=lambda targets: check_youtube(
                targets, caller=_caller()
            ),
        )
        found = findings(session, "youtube")
        assert found
        assert all(f.published_at == datetime(2026, 9, 16, 8, 30) for f in found)

    body = client.get(
        "/dashboard/takedowns?key=test-admin-key&platform=youtube"
    ).text
    assert "2026-09-16 08:30" in body
