"""YouTube-specific structuring.

Nothing is read off a screen here, so nothing is lossy. The API hands
over the video id, an exact `publishedAt`, the channel's id and title,
and integer counts. The work is mapping those names onto the same
columns the phone-captured platforms use, so one dashboard, one export
and one re-checker serve all three.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import base


def structure(payload: dict[str, Any]) -> dict[str, Any]:
    row = base.structure(payload, "youtube")

    # The API gives an exact timestamp, so it is parsed here rather
    # than left to the relative-date handling the feeds need.
    row["posted_on"] = _published(payload.get("published_at"))
    row["posted_at_raw"] = payload.get("published_at")

    # Integers, not rendered abbreviations. Saying otherwise would make
    # YouTube's counts look as uncertain as TikTok's.
    row["counts_approximate"] = False
    for column, key in (
        ("like_count", "like_count"),
        ("comment_count", "comment_count"),
        ("share_count", "view_count"),
    ):
        row[column] = _as_int(payload.get(key))
    row["save_count"] = None

    row["video_id"] = payload.get("video_id") or None
    row["author_handle"] = _handle(payload)
    row["author_name"] = payload.get("channel_title") or None
    return row


def _published(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _handle(payload: dict[str, Any]) -> str | None:
    """Prefer the @handle; fall back to the channel id.

    Either one finds the channel again, which is what the column is
    for. A channel id is uglier but never changes.
    """
    handle = payload.get("channel_handle")
    if handle:
        return str(handle).lstrip("@")
    channel = payload.get("channel_id")
    return str(channel) if channel else None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
