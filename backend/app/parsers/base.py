"""Shared structuring logic for capture payloads.

The on-device parsers normalise every platform onto one payload shape,
so the server-side work is the same for all of them: coerce displayed
counts to integers and record whether precision was lost. Per-platform
hooks exist for the fields that genuinely differ.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..counts import is_approximate, parse_count

_COUNT_FIELDS = {
    "like_count": "like_raw",
    "comment_count": "comment_raw",
    "share_count": "share_raw",
    "save_count": "save_raw",
}


def structure(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a raw capture payload onto structured post columns."""
    row: dict[str, Any] = {
        "author_handle": _clean(payload.get("author_handle")),
        "caption": _clean(payload.get("caption")),
        "music": _clean(payload.get("music")),
        "feed": _clean(payload.get("feed")),
        "is_ad": _as_bool(payload.get("is_ad")),
        "is_ai_generated": _as_bool(payload.get("is_ai_generated")),
    }

    approximate = False
    for column, source in _COUNT_FIELDS.items():
        raw = payload.get(source)
        row[column] = parse_count(raw)
        approximate = approximate or is_approximate(raw)
    row["counts_approximate"] = approximate

    return row


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_captured_at(value: Any) -> datetime | None:
    """Accept ISO-8601 or epoch milliseconds from the device."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value / 1000.0)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return datetime.utcfromtimestamp(int(text) / 1000.0)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
