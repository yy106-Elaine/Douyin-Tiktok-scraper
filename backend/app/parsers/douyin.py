"""Douyin-specific structuring."""
from __future__ import annotations

from typing import Any

from . import base

# Douyin labels its main feeds in Chinese; normalise to stable slugs so
# that analysis code is not written against UI strings.
_FEED_SLUGS = {
    "推荐": "recommend",
    "关注": "following",
    "朋友": "friends",
    "同城": "nearby",
    "热点": "trending",
}


def structure(payload: dict[str, Any]) -> dict[str, Any]:
    row = base.structure(payload, "douyin")
    if row.get("feed") in _FEED_SLUGS:
        row["feed"] = _FEED_SLUGS[row["feed"]]
    return row
