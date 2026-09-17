"""One row per video, however its identity arrived.

A post read off the screen and a link copied out of the share sheet are
two halves of the same observation: the screen has the caption and the
counts, the link has the id. They were stored separately and shown
separately, which left the dashboard asking the reader to join them by
eye. Everything a study needs about one video belongs on one row.

So this assembles that row. Captured posts supply most of them;
a shared link that has not been paired to any post gets a row of its
own rather than a second table, because an unpaired link is still a
video to re-check and hiding it in a separate section is how it gets
forgotten.

Publication time is chosen here too, best source first, and the source
is reported alongside the value -- see `posted_source`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .links import extract
from .models import SharedLink
from .parsers import PLATFORM_TABLES
from .snowflake import posted_at_from_video_id

#: A post whose id came from a link the device harvested for that exact
#: capture. The association is a fact, not an inference.
LINKED_EXACT = "linked (exact)"
#: A post whose id came from a link matched on time alone. Weaker, and
#: named so an analysis can exclude these rows.
LINKED_BY_TIME = "linked (by time)"
#: A post whose id was already on screen -- no link needed.
ID_ON_SCREEN = "id on screen"
#: A post row with no id yet: captured, but nothing to re-check with.
NO_LINK = "no link yet"
#: A copied link that resolved to an id but matched no captured post.
LINK_ONLY = "link only"
#: A copied short link that has not been followed to its real id yet.
NEEDS_RESOLVING = "needs resolving"


@dataclass(frozen=True)
class VideoRow:
    """Everything known about one video, from either source."""

    when: datetime
    participant_id: str
    platform: str
    state: str

    posted_at: datetime | None
    posted_display: str | None
    #: Where `posted_display` came from: "video id" (exact, decoded from
    #: the id), "screen" (parsed from what the interface rendered), or
    #: "as shown" (the rendered string, unparsed). Empty when unknown.
    posted_source: str

    video_id: str | None
    video_url: str | None
    author_handle: str | None
    author_name: str | None
    caption: str | None
    feed: str | None

    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    save_count: int | None = None

    counts_approximate: bool = False
    is_ad: bool | None = None
    is_ai_generated: bool | None = None


def publication(
    video_id: object, posted_on: datetime | None, posted_at_raw: str | None
) -> tuple[datetime | None, str | None, str]:
    """Best available publication time, with its provenance.

    The id decodes to the second and needs nothing from the interface,
    so it wins wherever it exists. What the screen showed is the
    fallback, and the unparsed string is better than an empty column.
    """
    derived = posted_at_from_video_id(video_id)
    if derived is not None:
        return derived, derived.strftime("%Y-%m-%d %H:%M"), "video id"
    if posted_on is not None:
        return posted_on, posted_on.strftime("%Y-%m-%d %H:%M"), "screen"
    if posted_at_raw:
        return None, posted_at_raw, "as shown"
    return None, None, ""


_STATE_BY_METHOD = {
    "fingerprint": LINKED_EXACT,
    "window": LINKED_BY_TIME,
}


def _post_state(post, method: str | None) -> str:
    if not post.video_id:
        return NO_LINK
    return _STATE_BY_METHOD.get(method or "", ID_ON_SCREEN)


def _row_from_post(post, platform: str, method: str | None = None) -> VideoRow:
    posted_at, display, source = publication(
        post.video_id, post.posted_on, post.posted_at_raw
    )
    return VideoRow(
        when=post.captured_at,
        participant_id=post.participant_id,
        platform=platform,
        state=_post_state(post, method),
        posted_at=posted_at,
        posted_display=display,
        posted_source=source,
        video_id=post.video_id,
        video_url=post.video_url,
        author_handle=post.author_handle,
        author_name=post.author_name,
        caption=post.caption,
        feed=post.feed,
        like_count=post.like_count,
        comment_count=post.comment_count,
        share_count=post.share_count,
        save_count=post.save_count,
        counts_approximate=bool(post.counts_approximate),
        is_ad=post.is_ad,
        is_ai_generated=post.is_ai_generated,
    )


def _row_from_link(link: SharedLink) -> VideoRow:
    posted_at, display, source = publication(link.video_id, None, None)
    # Before it is resolved a link has no canonical URL, only the short
    # one sitting inside the text that was copied. That one still opens
    # the video, which is what the row is for.
    target = link.canonical_url or extract(link.raw_text).raw_url
    return VideoRow(
        when=link.shared_at,
        participant_id=link.participant_id,
        platform=link.platform,
        state=LINK_ONLY if link.video_id else NEEDS_RESOLVING,
        posted_at=posted_at,
        posted_display=display,
        posted_source=source,
        video_id=link.video_id,
        video_url=target,
        author_handle=link.author_handle,
        author_name=None,
        # No post was matched, so there is no caption to show. The text
        # that was copied is the only description there is.
        caption=None,
        feed=None,
    )


def video_rows(session: Session, platform: str, limit: int) -> list[VideoRow]:
    """Merged rows for one platform, most recently seen first."""
    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return []
    model, _ = registered

    # How each paired link was matched, so a row can say whether its id
    # is a fact or a nearest-in-time guess.
    methods = {
        capture_id: method
        for capture_id, method in session.execute(
            select(SharedLink.matched_capture_id, SharedLink.pairing_method).where(
                SharedLink.matched_capture_id.isnot(None)
            )
        )
    }

    rows = [
        _row_from_post(post, platform, methods.get(post.capture_event_id))
        for post in session.scalars(
            select(model).order_by(model.captured_at.desc()).limit(limit)
        )
    ]

    # Only the links that no post row already accounts for: a paired
    # link's id is on its post's row, and showing it twice is the
    # duplication this module exists to remove.
    unpaired = session.scalars(
        select(SharedLink)
        .where(
            SharedLink.platform == platform,
            SharedLink.matched_capture_id.is_(None),
        )
        .order_by(SharedLink.shared_at.desc())
        .limit(limit)
    )
    rows.extend(_row_from_link(link) for link in unpaired)

    rows.sort(key=lambda row: row.when, reverse=True)
    return rows[:limit]
