"""Turn the abbreviated counts shown in app UIs back into integers.

Both apps render engagement counts in a lossy, locale-specific short
form: TikTok's English UI gives "74.9K" / "9M", Douyin's Chinese UI
gives "12.3万" / "1.2亿". The original value is NOT recoverable -- a
displayed "12.3万" is anything from 123000 to 123999. We return a
best-effort integer and the caller records that it is approximate.
"""
from __future__ import annotations

import re

# Ordered longest-first so that multi-char suffixes win.
_SUFFIXES: list[tuple[str, int]] = [
    ("亿", 100_000_000),
    ("万", 10_000),
    ("B", 1_000_000_000),
    ("M", 1_000_000),
    ("K", 1_000),
    ("W", 10_000),  # some romanised Douyin builds render 万 as W
]

_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_count(raw: str | int | None) -> int | None:
    """Parse a displayed count. Returns None when nothing numeric is found."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw

    text = str(raw).strip()
    if not text:
        return None

    upper = text.upper()
    multiplier = 1
    for suffix, factor in _SUFFIXES:
        haystack = upper if suffix.isascii() else text
        if suffix in haystack:
            multiplier = factor
            break

    match = _NUMBER.search(text.replace(",", ""))
    if not match:
        return None

    try:
        value = float(match.group(1))
    except ValueError:
        return None

    return int(value * multiplier)


def is_approximate(raw: str | int | None) -> bool:
    """True when the displayed value was abbreviated and precision was lost."""
    if raw is None or isinstance(raw, int):
        return False
    text = str(raw).upper()
    return any(s in text for s, _ in _SUFFIXES)
