"""Removing the rows the topic filter excluded.

1,072 of 1,126 YouTube rows were other things -- adult nappies, a
children's cartoon, Japanese vlogs. The ratio is a finding; the rows
are not the corpus. They go, after being written down.
"""
from __future__ import annotations

import csv

from app.db import SessionLocal
from app.models import CaptureEvent, LinkCheck
from app.parsers import PLATFORM_TABLES
from app.prune import excluded, prune, write_audit

YOUTUBE, _ = PLATFORM_TABLES["youtube"]
DOUYIN, _ = PLATFORM_TABLES["douyin"]


def _collect(client, titles):
    from app import youtube

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


_TITLES = {
    "keep": "我们是拉拉 女朋友日常",
    "nappies": "#卧床老人 #护理用品 #成人拉拉裤",
    "cartoon": "第86集：巴拉拉小魔仙 #我在抖音看动漫",
}


def test_the_excluded_rows_go_and_the_corpus_stays(client, api_key):
    _collect(client, _TITLES)

    with SessionLocal() as session:
        assert session.query(YOUTUBE).count() == 3
        assert {row.video_id for row in excluded(session, "youtube")} == {
            "nappies",
            "cartoon",
        }

        report = prune(session, "youtube", apply=True)
        assert report["rows"] == 2
        # The payload each was built from goes with it.
        assert report["events"] == 2

        kept = session.query(YOUTUBE).one()
        assert kept.video_id == "keep"
        assert session.query(CaptureEvent).count() == 1


def test_a_dry_run_removes_nothing(client, api_key):
    _collect(client, _TITLES)
    with SessionLocal() as session:
        assert prune(session, "youtube")["rows"] == 2
        assert session.query(YOUTUBE).count() == 3


def test_re_checks_of_a_removed_video_go_too(client, api_key):
    _collect(client, _TITLES)
    with SessionLocal() as session:
        session.add(
            LinkCheck(
                platform="youtube",
                video_id="nappies",
                url="https://www.youtube.com/watch?v=nappies",
                checked_at=__import__("datetime").datetime(2026, 9, 18, 12, 0),
                http_status=200,
            )
        )
        session.commit()

        assert prune(session, "youtube", apply=True)["checks"] == 1
        assert session.query(LinkCheck).count() == 0


def test_the_rows_are_written_down_before_they_go(client, api_key, tmp_path):
    """The classifier is fallible; deleting removes the ability to audit."""
    _collect(client, _TITLES)
    path = tmp_path / "excluded.csv"

    with SessionLocal() as session:
        rows = excluded(session, "youtube")
        assert write_audit(rows, path) == 2

    written = list(csv.DictReader(path.open(encoding="utf-8")))
    assert {row["video_id"] for row in written} == {"nappies", "cartoon"}
    assert all(row["relevance"] for row in written)
    assert any("拉拉裤" in row["caption"] for row in written)


def test_a_platform_with_no_topic_filter_is_never_pruned(client, api_key):
    """Douyin's rows are hidden when excluded, never deleted.

    It does have one rule now -- a caption must carry a community tag
    -- but that rule is a day old and has been rewritten twice.
    Marking is reversible and deleting is not, so prune leaves this
    platform alone whatever the filter says.
    """
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.ss.android.ugc.aweme",
                    "fingerprint": "douyin::a::b",
                    "captured_at": "2026-09-19T19:50:00Z",
                    "payload": {"author_name": "a", "caption": "完全无关的内容"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )
    with SessionLocal() as session:
        assert excluded(session, "douyin") == []
        assert prune(session, "douyin", apply=True)["rows"] == 0
        assert session.query(DOUYIN).count() == 1
