"""Shared structuring logic for capture payloads.

The on-device parsers normalise every platform onto one payload shape,
so the server-side work is the same for all of them: coerce displayed
counts to integers and record whether precision was lost. Per-platform
hooks exist for the fields that genuinely differ.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from ..counts import is_approximate, parse_count
from ..platforms import FILTERED_PLATFORMS
from ..relevance import classify

_COUNT_FIELDS = {
    "like_count": "like_raw",
    "comment_count": "comment_raw",
    "share_count": "share_raw",
    "save_count": "save_raw",
}


def structure(payload: dict[str, Any], platform: str) -> dict[str, Any]:
    """Map a raw capture payload onto structured post columns.

    [platform] decides only whether the topic filter runs: it is right
    for YouTube, whose keyword search returns whatever the API matched,
    and wrong for Douyin, which is sampled from community hashtags. See
    `FILTERED_PLATFORMS`.
    """
    row: dict[str, Any] = {
        "author_handle": _clean(payload.get("author_handle")),
        "author_name": _clean(payload.get("author_name")),
        "posted_at_raw": _posted_raw(payload.get("posted_at_raw")),
        "posted_on": _posted_on(payload.get("posted_at_raw")),
        "caption": _clean(payload.get("caption")),
        "music": _clean(payload.get("music")),
        "feed": _clean(payload.get("feed")),
        "is_ad": _as_bool(payload.get("is_ad")),
        "is_ai_generated": _as_bool(payload.get("is_ai_generated")),
        # Present only when the device found an id already on screen.
        # Obtained passively, so it needed no interaction with the app.
        "video_id": _video_id(payload.get("video_id_hint")),
        # Computed here so every platform gets it from one place --
        # the phone parsers and the YouTube API both land on this
        # function. Marked on arrival as well as by `remark`, so the
        # platform test has to live in both or an unfiltered platform
        # is filtered anyway for as long as nobody re-marks.
        "relevance": (
            classify(payload.get("caption"), payload.get("description"))
            if platform in FILTERED_PLATFORMS
            else None
        ),
    }

    approximate = False
    for column, source in _COUNT_FIELDS.items():
        raw = payload.get(source)
        row[column] = parse_count(raw)
        approximate = approximate or is_approximate(raw)
    row["counts_approximate"] = approximate

    return row


_ID_SHAPED = re.compile(r"^\d{18,19}$")

_FULL_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


_RELATIVE = re.compile(
    r"^(\d+)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|"
    r"d|days?|w|weeks?|mo|months?|y|years?)\s*ago$",
    re.IGNORECASE,
)

_RELATIVE_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    "mo": 2592000, "month": 2592000, "months": 2592000,
    "y": 31536000, "year": 31536000, "years": 31536000,
}


def resolve_posted_on(value: Any, reference: datetime | None = None) -> datetime | None:
    """Parse a publication date, absolutely or relative to [reference].

    A full date is taken as given. A relative one ("11h ago") is
    resolved against the moment of capture, which is not a guess: the
    offset and the reference are both known, so the result is accurate
    to the granularity the interface showed. Anything coarser than the
    unit is the interface's rounding, not this function's.

    Partial dates ("5-31") are still refused. There the year is genuinely
    missing, and inferring it would fabricate the variable a takedown
    study measures from.
    """
    if value is None:
        return None
    text = str(value).strip().lstrip("·").strip()
    if not text:
        return None

    if match := _FULL_DATE.match(text):
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    if match := _RELATIVE.match(text):
        if reference is None:
            return None
        seconds = _RELATIVE_UNITS.get(match.group(2).lower())
        if seconds is None:
            return None
        return reference - timedelta(seconds=int(match.group(1)) * seconds)

    return None


def _posted_on(value: Any) -> datetime | None:
    """Absolute dates only; the caller resolves relative ones."""
    return resolve_posted_on(value, reference=None)


def _posted_raw(value: Any) -> str | None:
    """The displayed date, without the separator bullet the UI draws.

    The device strips it too, but a stored value should not depend on
    which side got there first.
    """
    text = _clean(value)
    return text.lstrip("·").strip() or None if text else None


def _video_id(value: Any) -> str | None:
    """Accept a hint only if it looks like a platform video id."""
    if value is None:
        return None
    text = str(value).strip()
    return text if _ID_SHAPED.match(text) else None


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
