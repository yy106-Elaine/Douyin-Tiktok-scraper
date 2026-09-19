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

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .links import extract
from .models import SharedLink
from .platforms import API_PLATFORMS
from .relevance import HIDDEN
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
    #: Where `posted_display` came from: "video id" (exact, decoded
    #: from the id), "api" (exact, the platform said so), "screen"
    #: (parsed from what the interface rendered), or "as shown" (the
    #: rendered string, unparsed). Empty when unknown.
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

    #: Null when in scope; otherwise why the row is out. See
    #: app/relevance.py.
    relevance: str | None = None


def publication(
    video_id: object,
    posted_on: datetime | None,
    posted_at_raw: str | None,
    platform: str | None = None,
) -> tuple[datetime | None, str | None, str]:
    """Best available publication time, with its provenance.

    The id decodes to the second and needs nothing from the interface,
    so it wins wherever it exists. What the screen showed is the
    fallback, and the unparsed string is better than an empty column.

    `platform` only changes the label: YouTube's `posted_on` came from
    its API and is exact, so calling it "from screen" would understate
    it as badly as calling a rendered "11h ago" exact would overstate
    the others.
    """
    derived = posted_at_from_video_id(video_id)
    if derived is not None:
        return derived, derived.strftime("%Y-%m-%d %H:%M"), "video id"
    if posted_on is not None:
        source = "api" if (platform or "").startswith("youtube") else "screen"
        return posted_on, posted_on.strftime("%Y-%m-%d %H:%M"), source
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
        post.video_id, post.posted_on, post.posted_at_raw, platform
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
        relevance=post.relevance,
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


#: What `show` may ask for beyond a specific exclusion reason.
SHOW_ALL = "all"
SHOW_EXCLUDED = "excluded"


def in_scope_filter(model, platform: str):
    """The corpus condition, for any query against a post table.

    One definition because there are two callers -- the dashboard and
    the CSV export -- and they had already drifted: the export was
    dropping hand-collected rows the dashboard kept.

    A phone row with an id is one whose link a person copied by hand,
    one video at a time. Its caption is often truncated to "...more"
    or absent, so the text is no evidence about the video, and these
    are the rows that cost the most to collect. YouTube gets no such
    exemption: the API chose those results.
    """
    condition = model.relevance.notin_(HIDDEN) | model.relevance.is_(None)
    if platform not in API_PLATFORMS:
        condition = condition | model.video_id.isnot(None)
    return condition


def _identity(model):
    """What counts as one video, for a distinct count.

    The video id where there is one. Otherwise the capture
    fingerprint, because a phone post with no copied link is still the
    same post when it is seen again the next day -- the phone
    platforms deliberately store one observation per post per day, so
    counting rows there would count days, not videos.
    """
    from sqlalchemy import func

    from .models import CaptureEvent

    return func.coalesce(model.video_id, CaptureEvent.fingerprint)


def first_seen(session: Session, platform: str) -> dict[str, datetime]:
    """Earliest observation of each distinct video in scope.

    Both counts below are about *new* videos, so both need first
    observation rather than any observation. Filtering rows by time
    instead would make a phone post seen every day look new every day
    -- the phone platforms store one observation per post per day on
    purpose.
    """
    from .models import CaptureEvent

    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return {}
    model, _ = registered

    earliest: dict[str, datetime] = {}
    for identity, captured_at in session.execute(
        select(_identity(model), model.captured_at)
        .select_from(model)
        .join(CaptureEvent, CaptureEvent.id == model.capture_event_id)
        .where(in_scope_filter(model, platform))
    ):
        if identity is None:
            continue
        if identity not in earliest or captured_at < earliest[identity]:
            earliest[identity] = captured_at
    return earliest


def unique_in_scope(
    session: Session, platform: str, since: datetime | None = None
) -> int:
    """Distinct videos in scope, or those first seen since `since`."""
    earliest = first_seen(session, platform)
    if since is None:
        return len(earliest)
    return sum(1 for moment in earliest.values() if moment >= since)


def daily_counts(
    session: Session, platform: str, days: int = 7, now: datetime | None = None
) -> list[tuple[str, int]]:
    """Distinct in-scope videos first collected on each of the last `days`."""
    moment = now or datetime.utcnow()
    start = (moment - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    counts: dict[str, int] = {}
    for captured_at in first_seen(session, platform).values():
        if captured_at >= start:
            key = captured_at.date().isoformat()
            counts[key] = counts.get(key, 0) + 1

    return [
        ((start + timedelta(days=offset)).date().isoformat(),
         counts.get((start + timedelta(days=offset)).date().isoformat(), 0))
        for offset in range(days)
    ]


def video_rows(
    session: Session, platform: str, limit: int, show: str = ""
) -> list[VideoRow]:
    """Merged rows for one platform, most recently seen first.

    `show` selects what to list: "" for the rows in scope, "all" for
    everything, "excluded" for only the hidden rows, or one exclusion
    reason to review that category on its own. Reviewing by category is
    the point -- a filter is only worth trusting once someone has read
    what it removed, and reading 500 mixed rows is not reading.
    """
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

    statement = select(model).order_by(model.captured_at.desc())
    in_scope = in_scope_filter(model, platform)

    if show == SHOW_ALL:
        pass
    elif show == SHOW_EXCLUDED:
        statement = statement.where(~in_scope)
    elif show:
        # One named reason. Still intersected with the carve-out, so a
        # hand-collected row never appears as excluded when it is not.
        statement = statement.where(model.relevance == show, ~in_scope)
    else:
        statement = statement.where(in_scope)
    rows = [
        _row_from_post(post, platform, methods.get(post.capture_event_id))
        for post in session.scalars(statement.limit(limit))
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
    return _one_row_per_video(rows)[:limit]


def _one_row_per_video(rows: list[VideoRow]) -> list[VideoRow]:
    """Collapse rows that a video id proves are the same video.

    A post is stored once per capture, and a caption that had not
    rendered yet makes the second capture look like a different post:
    the same author and the same counts under two identities, because
    identity falls back to author plus caption. Once a link has given
    both rows the same id, they are provably one video, and a table
    that lists it twice is a table nobody can count.

    Rows with no id are left alone. Without one there is no proof, and
    guessing that two rows are the same video would silently merge two
    videos by the same author -- a worse error than showing two rows.

    The kept row is the fullest, field by field, so a caption read on
    the second pass is not lost to a first pass that missed it.
    """
    at: dict[str, int] = {}
    out: list[VideoRow] = []
    for row in rows:
        if not row.video_id:
            out.append(row)
            continue
        index = at.get(row.video_id)
        if index is None:
            at[row.video_id] = len(out)
            out.append(row)
            continue
        out[index] = _filled(out[index], row)

    return out


#: Filled from a second sighting when the first left them empty. Never
#: `when` or `video_id`: the first sighting is the one first_seen means,
#: and the id is what proved the two are the same row.
_MERGEABLE = (
    "posted_at",
    "posted_display",
    "posted_source",
    "video_url",
    "author_handle",
    "author_name",
    "caption",
    "feed",
    "like_count",
    "comment_count",
    "share_count",
    "save_count",
    "is_ad",
    "is_ai_generated",
)


def _filled(held: VideoRow, other: VideoRow) -> VideoRow:
    """`held` with its empty fields taken from `other`. Rows are frozen."""
    gaps = {}
    for field in _MERGEABLE:
        if getattr(held, field, None) in (None, ""):
            value = getattr(other, field, None)
            if value not in (None, ""):
                gaps[field] = value
    return replace(held, **gaps) if gaps else held
