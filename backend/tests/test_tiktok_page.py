"""Reading a TikTok video page.

Same shape as Douyin's, different spellings -- `id` for `aweme_id`,
`stats` for `statistics`, `createTime` for `create_time`. The fixture
below is TikTok's `itemStruct` as the page embeds it.
"""
from __future__ import annotations

import json

from app.tiktok_page import file_urls, video_facts, video_url


def _item(video_id: str = "7687820515369510629", **over) -> dict:
    return {
        "id": video_id,
        "desc": over.get("desc", "#Chinesecouple #Chineselesbian #wlw #fyp"),
        "createTime": over.get("createTime", 1789917000),
        "author": {
            "uniqueId": over.get("uniqueId", "rulebreaker2424"),
            "nickname": over.get("nickname", "Rule Breaker🌈"),
            "secUid": "MS4wLjABAAAAexample",
        },
        "stats": {
            "diggCount": over.get("digg", 0),
            "commentCount": 33,
            "shareCount": 466,
            "collectCount": 12,
        },
        "video": {
            "playAddr": "https://cdn.tiktok/play.mp4",
            "bitrateInfo": [
                {"PlayAddr": {"UrlList": ["https://cdn.tiktok/rung.mp4"]}}
            ],
        },
    }


def _page(item: dict) -> str:
    blob = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}}
    return (
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        + json.dumps(blob, ensure_ascii=False)
        + "</script>"
    )


def test_the_record_embedded_in_the_page_is_read():
    facts = video_facts(_page(_item()))
    assert facts.video_id == "7687820515369510629"
    assert facts.author_name == "Rule Breaker🌈"
    # uniqueId IS the @handle -- no second visit, unlike Douyin's 抖音号.
    assert facts.author_handle == "rulebreaker2424"
    assert facts.caption == "#Chinesecouple #Chineselesbian #wlw #fyp"
    assert facts.comment_count == 33
    assert facts.share_count == 466
    assert facts.parsed_by == "embedded"


def test_zero_likes_is_a_reading_not_a_missing_value():
    assert video_facts(_page(_item())).like_count == 0


def test_the_api_answer_beats_the_embedded_one():
    """A captured XHR is the record the app itself reads."""
    api = {"itemInfo": {"itemStruct": _item(nickname="from the api")}}
    facts = video_facts(_page(_item(nickname="from the html")), [api])
    assert facts.author_name == "from the api"
    assert facts.parsed_by == "api"


def test_a_page_with_nothing_in_it_says_so():
    assert video_facts("<html></html>").is_empty()


def test_the_caption_alone_is_read_off_the_surface():
    html = '<meta property="og:description" content="a caption and no counts">'
    facts = video_facts(html)
    assert facts.caption == "a caption and no counts"
    assert facts.parsed_by == "surface"
    assert facts.like_count is None


def test_both_kinds_of_address_are_offered():
    """A bare string and the capitalised ladder under bitrateInfo."""
    urls = file_urls(payloads=[{"itemInfo": {"itemStruct": _item()}}])
    assert urls == ["https://cdn.tiktok/play.mp4", "https://cdn.tiktok/rung.mp4"]


def test_a_record_about_another_video_offers_no_address():
    """The same guard as Douyin's, for the same reason.

    A page carries its neighbours' records too, so "no conflicting id"
    is not "this is the right video".
    """
    other = [{"itemInfo": {"itemStruct": _item("7000000000000000000")}}]
    assert file_urls(payloads=other, video_id="7687820515369510629") == []
    anonymous = [{"video": {"playAddr": "https://cdn.tiktok/x.mp4"}}]
    assert file_urls(payloads=anonymous, video_id="7687820515369510629") == []


def test_the_handle_is_part_of_the_address():
    assert video_url("7687820515369510629", "rulebreaker2424") == (
        "https://www.tiktok.com/@rulebreaker2424/video/7687820515369510629"
    )
    # Unknown: TikTok resolves by id and redirects.
    assert video_url("7687820515369510629") == (
        "https://www.tiktok.com/@i/video/7687820515369510629"
    )
    assert "@rulebreaker2424" in video_url("7687820515369510629", "@rulebreaker2424")
