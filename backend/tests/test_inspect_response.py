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
        ["https://mcs.zijieapi.com/list", {"ok": 1}],
        ["https://mon.zijieapi.com/monitor_web/settings/browser-settings",
         {"settings": {}}],
    ]), encoding="utf-8")

    said = "\n".join(report(path))
    assert "no aweme/detail or aweme/post body" in said


def test_long_values_are_summarised_not_dumped(tmp_path) -> None:
    """A record body is a megabyte; the answer is in its skeleton."""
    path = tmp_path / "w.responses.json"
    path.write_text(json.dumps([
        ["https://www.douyin.com/aweme/v1/web/aweme/detail/",
         {"status_msg": "x" * 5000, "aweme_detail": None}],
    ]), encoding="utf-8")

    said = "\n".join(report(path))
    assert len(said) < 1000
