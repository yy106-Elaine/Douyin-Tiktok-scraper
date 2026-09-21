"""Reading a Douyin page fetched from a computer.

The phone reaches posts the web search will not return; that is why
it collects. But what it reads off a feed has to be stitched to a
copied link afterwards, and that stitch produced every wrong row in
this study. A page fetched by id needs no stitch.

Written without access to Douyin, so the fixtures here are the
shapes the share host is documented to serve rather than responses
anyone has seen. What the tests pin is the reading: that an embedded
record is preferred, that the surface is a fallback and says so, and
that Beijing time is converted.
"""
from __future__ import annotations

import json
from datetime import datetime

from app.douyin_page import author_facts, video_facts

_RECORD = {
    "aweme_id": "7687820515369510629",
    "desc": "再来一次 我不会再与你相恋#wlw",
    # 2026-09-20 23:10 Beijing.
    "create_time": 1789917000,
    "author": {
        "nickname": "35",
        "sec_uid": "MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS",
        "unique_id": "70056222078",
    },
    "statistics": {
        "digg_count": 0,
        "comment_count": 0,
        "share_count": 2,
        "collect_count": 1,
    },
}


def _page(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False)
    return f"<html><head><script>window._ROUTER_DATA = {blob};</script></head></html>"


def test_the_embedded_record_answers_everything():
    facts = video_facts(
        _page({"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [_RECORD]}}}})
    )
    assert facts.video_id == "7687820515369510629"
    assert facts.author_name == "35"
    assert facts.author_handle == "70056222078"
    assert facts.caption == "再来一次 我不会再与你相恋#wlw"
    assert facts.share_count == 2
    assert facts.collect_count == 1
    # Zero is a reading, not a missing value.
    assert facts.like_count == 0
    assert facts.comment_count == 0
    assert facts.posted_on == datetime(2026, 9, 20, 15, 10)
    assert facts.parsed_by == "embedded"


def test_the_record_is_found_wherever_it_sits():
    """These blobs are undocumented and their shape changes."""
    facts = video_facts(_page({"a": [{"b": {"c": [{"deep": _RECORD}]}}]}))
    assert facts.caption == "再来一次 我不会再与你相恋#wlw"


def test_a_brace_in_a_caption_does_not_end_the_blob():
    record = {**_RECORD, "desc": "笑死 {这是一个} 括号 #wlw"}
    facts = video_facts(_page({"item_list": [record]}))
    assert facts.caption == "笑死 {这是一个} 括号 #wlw"
    assert facts.share_count == 2


def test_the_surface_is_a_fallback_and_says_so():
    html = (
        '<meta property="og:description" content="再来一次 我不会再与你相恋#wlw">'
        "<div>发布时间：2026-09-20 23:10</div>"
    )
    facts = video_facts(html)
    assert facts.caption == "再来一次 我不会再与你相恋#wlw"
    assert facts.parsed_by == "surface"
    # No counts off the surface, and the row should not imply any.
    assert facts.like_count is None


def test_the_page_prints_beijing_time_and_the_column_holds_utc():
    html = "<div>发布时间：2026-09-20 23:10</div>"
    assert video_facts(html).posted_on == datetime(2026, 9, 20, 15, 10)


def test_a_profile_yields_the_handle():
    profile = {
        "user": {
            "nickname": "35",
            "sec_uid": "MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS",
            "unique_id": "70056222078",
            "signature": "你过得好我们的分开才有意义",
            "ip_location": "湖南",
            "follower_count": 1,
            "following_count": 1,
            "total_favorited": 142,
            "aweme_count": 2,
        }
    }
    facts = author_facts(_page(profile))
    assert facts.author_handle == "70056222078"
    assert facts.author_name == "35"
    assert facts.ip_location == "湖南"
    assert facts.total_favorited == 142
    assert facts.parsed_by == "embedded"


def test_a_profile_read_off_the_surface_still_gives_the_handle():
    html = "<span>抖音号：70056222078</span><span>IP属地：湖南</span>"
    facts = author_facts(html)
    assert facts.author_handle == "70056222078"
    assert facts.ip_location == "湖南"
    assert facts.parsed_by == "surface"


def test_a_page_that_says_nothing_is_empty_not_wrong():
    facts = video_facts("<html><body>请下载抖音 App</body></html>")
    assert facts.is_empty()


def test_render_data_is_percent_encoded_and_still_read():
    """douyin.com's own pages, as opposed to the share host.

    Five video pages came back "surface only" -- a caption off a meta
    tag, no counts -- because the state is in a script tag rather
    than an assignment, and the JSON inside it is percent-encoded.
    """
    import urllib.parse

    payload = {"aweme": {"detail": _RECORD}}
    blob = urllib.parse.quote(json.dumps(payload, ensure_ascii=False))
    html = f'<script id="RENDER_DATA" type="application/json">{blob}</script>'

    facts = video_facts(html)
    assert facts.parsed_by == "embedded"
    assert facts.author_name == "35"
    assert facts.like_count == 0
    assert facts.share_count == 2


def test_the_account_id_is_read_even_off_the_surface():
    """It is what the profile pass is keyed on.

    A video page that yields nothing else still turns into a readable
    author if this comes out of it.
    """
    html = (
        '<a href="/user/MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS">35</a>'
        "<div>发布时间：2026-09-20 23:10</div>"
    )
    facts = video_facts(html)
    assert facts.sec_uid == "MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS"
    assert facts.parsed_by == "surface"


def test_the_api_response_is_preferred_and_labelled():
    """douyin.com puts nothing about the video in its HTML.

    Its `RENDER_DATA` holds the page shell -- the video's id does not
    appear in it at all -- and the record arrives in an XHR after
    hydration. Captured, that response is the aweme record itself.
    """
    payload = {"aweme_detail": _RECORD}
    facts = video_facts("<html>没有数据</html>", [payload])

    assert facts.parsed_by == "api"
    assert facts.author_name == "35"
    assert facts.like_count == 0
    assert facts.share_count == 2
    assert facts.posted_on == datetime(2026, 9, 20, 15, 10)


def test_the_api_answer_beats_the_surface():
    html = '<meta property="og:description" content="标题里混着作者名于2026">'
    facts = video_facts(html, [{"aweme_detail": _RECORD}])
    assert facts.caption == "再来一次 我不会再与你相恋#wlw"


def test_a_profile_api_response_gives_the_handle():
    payload = {
        "user": {
            "nickname": "35",
            "sec_uid": "MS4wLjABAAAAQ3osBXG0LqnkGyPJZ11GS",
            "unique_id": "70056222078",
            "follower_count": 1,
        }
    }
    facts = author_facts("", [payload])
    assert facts.author_handle == "70056222078"
    assert facts.parsed_by == "api"
