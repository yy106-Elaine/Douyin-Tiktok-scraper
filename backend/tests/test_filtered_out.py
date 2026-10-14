"""Douyin's third way of saying a post is gone.

The first two are visible: the page carries 你要观看的视频不存在, or
the site hands over a different video's record. This one is in the
JSON -- `aweme/detail` answers 200, `status_code: 0`, a null
`aweme_detail`, and a `filter_detail` naming the id asked for.

Nothing looked at it for a month, so those pages were filed as
"read, nothing on the page", which is recorded as *unknown*. On the
video platform that was 16% of a pass, and unlike the other two
faults found this week it runs in the direction that under-states
the study's own finding.
"""
from __future__ import annotations

from app.douyin_page import filtered_out
from app.recheck import _BY_EVIDENCE, API_FILTERED, GONE

ASKED = "7686427432119291057"


def _refusal(video_id: str = ASKED, reason: str = "status_self_see") -> dict:
    return {
        "status_code": 0,
        "aweme_detail": None,
        "filter_detail": {
            "aweme_id": video_id,
            "filter_reason": reason,
            "detail_msg": "因作品权限或已被删除，无法观看，去看看其他作品吧",
            "notice": "抱歉，作品不见了",
        },
    }


def test_a_filtered_post_is_gone_not_unknown() -> None:
    assert filtered_out([_refusal()], ASKED) == "status_self_see"
    assert _BY_EVIDENCE[API_FILTERED] == GONE


def test_a_filter_with_no_reason_is_still_gone() -> None:
    """One of the three peeked pages had an empty `filter_reason`:
    filtered, with nothing said about why. That is still gone, and
    "Douyin would not say" is a finding about Douyin, so it is
    recorded under its own name rather than dropped."""
    assert filtered_out([_refusal(reason="")], ASKED) == "unstated"
    assert filtered_out([_refusal(reason="   ")], ASKED) == "unstated"


def test_a_filter_about_another_post_is_not_evidence_about_this_one() -> None:
    """A page carries the records of a dozen posts, and a notice
    about one of them says nothing about the rest. Matched on the
    id, never on position."""
    assert filtered_out([_refusal(video_id="999")], ASKED) is None


def test_a_filter_beside_a_live_record_is_not_a_removal() -> None:
    """`filter_detail` next to a populated `aweme_detail` is the
    site annotating a post it is still serving."""
    body = _refusal()
    body["aweme_detail"] = {"aweme_id": ASKED, "desc": "still here"}
    assert filtered_out([body], ASKED) is None


def test_an_ordinary_record_is_not_a_removal() -> None:
    assert filtered_out([{"aweme_detail": {"aweme_id": ASKED}}], ASKED) is None
    assert filtered_out([], ASKED) is None
    assert filtered_out(None, ASKED) is None


def test_it_is_found_however_deep_the_body_buries_it() -> None:
    assert filtered_out([{"data": {"result": _refusal()}}], ASKED) == \
        "status_self_see"


def test_the_id_is_compared_as_text() -> None:
    """Douyin sends the id as a string in some bodies and a number
    in others, and the pass holds it as a string."""
    body = _refusal()
    body["filter_detail"]["aweme_id"] = int(ASKED)
    assert filtered_out([body], ASKED) == "status_self_see"
