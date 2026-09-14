"""TikTok-specific structuring."""
from __future__ import annotations

from typing import Any

from . import base

_FEED_SLUGS = {
    "For You": "recommend",
    "Following": "following",
    "Friends": "friends",
    "Explore": "explore",
    "LIVE": "live",
}


def structure(payload: dict[str, Any]) -> dict[str, Any]:
    row = base.structure(payload)
    if row.get("feed") in _FEED_SLUGS:
        row["feed"] = _FEED_SLUGS[row["feed"]]
    return row
