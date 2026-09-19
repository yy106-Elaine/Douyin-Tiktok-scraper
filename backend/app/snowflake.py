"""Recover a post's publication time from its video id.

Both platforms mint video ids with a Snowflake-style scheme: the high
32 bits of the 64-bit id are the creation time in whole seconds since
the Unix epoch. So an id is not only an identifier -- it carries the
moment the post was created, to the second, with no request to the
platform and no dependence on what the interface happened to render.

That matters here more than it looks. The feed shows publication time
as "11h ago", or as a partial date, or not at all; a takedown study
measures from publication, so a time-to-removal built on the rendered
string inherits that string's rounding. The id does not round.

The derivation is not stored. `video_id` is the stored fact and this is
a pure function of it, so there is no second copy to fall out of date
and no migration to run.

Confidence differs by platform and is reported rather than assumed:
TikTok's layout is long-established and reproducible against any post
whose date is known. Douyin runs on the same infrastructure and the
same arithmetic gives plausible times, but no Douyin post has been
checked against a known publication date on a device here, so the
result is labelled unverified until one has been. See
`docs/METHODOLOGY.md`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: Ids that decode outside this range are not Snowflakes we understand
#: -- a synthetic id, a different scheme, or an id read off the screen
#: wrongly. Better to return nothing than a date from 1970 that would
#: silently become a data point.
_EARLIEST = datetime(2016, 1, 1)

#: Platforms whose layout has been confirmed against known posts.
#:
#: Douyin is still not one, and an attempt to move it here is worth
#: recording because of how it failed. Id 7686818714507271786 decodes
#: to 2026-09-18 10:22:28, which is 15.8 hours before the capture that
#: carried it, while the feed at that moment rendered 17小时前 -- a
#: mismatch of over an hour, not a rounding difference.
#:
#: But the two numbers describe different videos. The id came from one
#: row and the 17小时前 was read off another in the same screen dump,
#: because the Douyin parser was not capturing 发布时间 at all, so no
#: row carried both. The comparison was never valid in either
#: direction: it neither confirms the derivation nor refutes it.
#:
#: The parser now reads 发布时间, so a row collected from here on has
#: an independent reading beside its id. Check one of those -- same
#: row, both values -- and move douyin in.
_VERIFIED = {"tiktok"}


def posted_at_from_video_id(
    video_id: object, now: datetime | None = None
) -> datetime | None:
    """The post's creation time in naive UTC, or None if undecodable."""
    if video_id is None:
        return None
    text = str(video_id).strip()
    if not text.isdigit() or not 18 <= len(text) <= 19:
        return None

    seconds = int(text) >> 32
    try:
        moment = datetime.utcfromtimestamp(seconds)
    except (OverflowError, OSError, ValueError):
        return None

    # A post cannot have been published in the future. A day of slack
    # absorbs a clock that is merely wrong rather than meaningless.
    ceiling = (now or datetime.now(timezone.utc).replace(tzinfo=None))
    if not _EARLIEST <= moment <= ceiling + timedelta(days=1):
        return None
    return moment


def derivation_is_verified(platform: str | None) -> bool:
    """Whether this platform's layout has been checked against a post."""
    return (platform or "").lower() in _VERIFIED
