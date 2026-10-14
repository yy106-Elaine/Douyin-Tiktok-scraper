"""Reading a saved response body for why the parser found nothing.

Three video pages filed as unreadable turned out to have requested
`aweme/detail`, received 200, and carried the id in the answer. So
the record arrived and the parser got nothing out of it, and the
question moved from the network to the body.
"""
from __future__ import annotations

import json

from app.inspect_response import report


def test_a_record_that_is_null_is_called_out(tmp_path) -> None:
    """A 200 with no record in it is not the same as a page that
    never asked, and the pass currently files both as "read, nothing
    on the page"."""
    path = tmp_path / "x.responses.json"
    path.write_text(json.dumps([
        ["https://www.douyin.com/aweme/v1/web/aweme/detail/",
         {"status_code": 0, "aweme_detail": None,
          "filter_detail": {"notice": "该作品已下架", "detail_msg": ""}}],
    ]), encoding="utf-8")

    said = "\n".join(report(path))

    assert "NULL — the record is not here" in said
    assert "该作品已下架" in said
    assert "status_code: 0" in said


def test_a_record_that_is_present_says_so(tmp_path) -> None:
    path = tmp_path / "y.responses.json"
    path.write_text(json.dumps([
        ["https://www.douyin.com/aweme/v1/web/aweme/detail/",
         {"status_code": 0,
          "aweme_detail": {"aweme_id": "7", "desc": "hi", "author": {}}}],
    ]), encoding="utf-8")

    said = "\n".join(report(path))
    assert "present" in said


def test_the_telemetry_bodies_are_skipped(tmp_path) -> None:
    """A peeked page holds thirty-odd responses and three matter."""
    path = tmp_path / "z.responses.json"
    path.write_text(json.dumps([
        {"url": "https://mcs.zijieapi.com/list", "body": {"ok": 1}},
        {"url": "https://mon.zijieapi.com/monitor_web/settings/"
                "browser-settings", "body": {"settings": {}}},
    ]), encoding="utf-8")

    said = "\n".join(report(path))
    assert "2 response(s) in this file, none of them" in said


def test_long_values_are_summarised_not_dumped(tmp_path) -> None:
    """A record body is a megabyte; the answer is in its skeleton."""
    path = tmp_path / "w.responses.json"
    path.write_text(json.dumps([
        ["https://www.douyin.com/aweme/v1/web/aweme/detail/",
         {"status_msg": "x" * 5000, "aweme_detail": None}],
    ]), encoding="utf-8")

    said = "\n".join(report(path))
    assert len(said) < 1000


def test_the_shape_peek_actually_writes(tmp_path) -> None:
    """peek writes `[{"url": …, "body": …}]`, not pairs.

    The first version of this reader assumed pairs, unpacked each
    dict into its two key *names*, matched no endpoint, and printed
    "no aweme/detail body in this file" -- which reads as a fact
    about Douyin and was a fact about my guess at a file format.
    Same failure as asking for the constant's name instead of its
    value: an empty result that looks like an answer.
    """
    path = tmp_path / "real.responses.json"
    path.write_text(json.dumps([
        {"url": "https://www.douyin.com/aweme/v1/web/aweme/detail/",
         "body": {"status_code": 0, "aweme_detail": None}},
    ], ensure_ascii=False), encoding="utf-8")

    said = "\n".join(report(path))
    assert "NULL — the record is not here" in said


def test_an_unreadable_file_says_it_is_a_fault_here(tmp_path) -> None:
    """"Nothing matched" and "I could not read this" are different,
    and only one of them is about the data."""
    path = tmp_path / "odd.responses.json"
    path.write_text(json.dumps(["just", "strings"]), encoding="utf-8")

    said = "\n".join(report(path))
    assert "a fault here, not a finding" in said
