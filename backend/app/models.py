"""ORM models.

Layout mirrors the two-layer approach the reference system used: every
capture is stored verbatim in `capture_events` (so a parser bug is
always recoverable by re-parsing), and a per-platform structured table
holds the typed fields used for analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    participant_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    api_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CaptureEvent(Base):
    """One de-duplicated observation of one post on one participant's screen."""

    __tablename__ = "capture_events"
    __table_args__ = (
        UniqueConstraint(
            "participant_id", "fingerprint", "capture_date", name="uq_capture_daily"
        ),
        Index("ix_capture_platform_time", "platform", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(32), index=True)

    # Stable identity for the post as seen on screen. Becomes the real
    # video id once a shared link has been paired in (see pairing.py).
    fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    capture_date: Mapped[str] = mapped_column(String(10))

    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Verbatim JSON of everything the on-device parser produced.
    payload: Mapped[str] = mapped_column(Text)


class _PostMixin:
    """Structured columns shared by every platform table."""

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_event_id: Mapped[int] = mapped_column(
        ForeignKey("capture_events.id"), index=True
    )
    participant_id: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    #: The `@handle` -- unique, stable, and the only form that can be
    #: used to find the account again or contact its owner. Often
    #: absent, because the feed usually renders only a display name.
    author_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    #: The display name. Not unique, changeable, frequently carries
    #: emoji. Present on nearly every capture.
    author_name: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)

    #: Publication date exactly as the interface rendered it. Kept
    #: verbatim because the form varies: a full date on older posts, a
    #: partial or relative one on recent posts.
    posted_at_raw: Mapped[str | None] = mapped_column(String(64))
    #: Parsed only when the raw value carried a full, unambiguous date.
    #: A takedown study measures from publication, so this is what makes
    #: time-to-removal a property of the platform rather than of when
    #: this device happened to scroll past.
    posted_on: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    music: Mapped[str | None] = mapped_column(Text)
    #: Which surface a post was seen on: a feed tab, or
    #: "search:<keyword>[,<keyword>...]". Wide enough for a whole
    #: keyword list, since a YouTube row names every keyword that
    #: surfaced it.
    feed: Mapped[str | None] = mapped_column(String(255))

    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    share_count: Mapped[int | None] = mapped_column(Integer)
    save_count: Mapped[int | None] = mapped_column(Integer)

    # True when any count above came from an abbreviated display value
    # ("12.3万" / "74.9K") and is therefore approximate.
    counts_approximate: Mapped[bool] = mapped_column(Boolean, default=False)

    is_ad: Mapped[bool | None] = mapped_column(Boolean)
    is_ai_generated: Mapped[bool | None] = mapped_column(Boolean)

    #: Null when the row is in scope for the study, otherwise why it
    #: is not -- see app/relevance.py. A keyword search returns what
    #: the platform matched, not what the study is about, and in
    #: Chinese the search terms sit inside unrelated words. Marked
    #: rather than dropped: a video deleted by a filter is a video
    #: whose disappearance can never be observed, and nothing in the
    #: data would show it had been there.
    relevance: Mapped[str | None] = mapped_column(String(32), index=True)

    # Populated only once a shared link has been paired to this post.
    video_id: Mapped[str | None] = mapped_column(String(128), index=True)
    video_url: Mapped[str | None] = mapped_column(String(512))


class DouyinPost(_PostMixin, Base):
    __tablename__ = "douyin_posts"


class TikTokPost(_PostMixin, Base):
    __tablename__ = "tiktok_posts"


class YouTubePost(_PostMixin, Base):
    """Same columns, different provenance.

    YouTube is read through its Data API rather than off a screen, so
    every field here is exact: the id is given, `posted_on` is the
    API's own publishedAt, and the counts are integers rather than
    rendered abbreviations. `counts_approximate` is therefore false for
    these rows, and that difference between platforms belongs in a
    write-up -- see docs/METHODOLOGY.md.
    """

    __tablename__ = "youtube_posts"


class SharedLink(Base):
    """A link the participant actively shared into the app.

    This is the only path that yields a real video id, so it is stored
    independently of the passive capture stream and paired afterwards.
    """

    __tablename__ = "shared_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)

    raw_text: Mapped[str] = mapped_column(Text)
    video_id: Mapped[str | None] = mapped_column(String(128), index=True)
    author_handle: Mapped[str | None] = mapped_column(String(255))
    canonical_url: Mapped[str | None] = mapped_column(String(512))

    shared_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    #: The capture this link was harvested for, when the device knew.
    fingerprint: Mapped[str | None] = mapped_column(String(255), index=True)

    matched_capture_id: Mapped[int | None] = mapped_column(
        ForeignKey("capture_events.id"), index=True
    )

    #: How the link was matched to a post: "fingerprint" (exact, the
    #: device harvested it for a known capture), "window" (heuristic,
    #: nearest capture in time), or null when unpaired. Analysis should
    #: be able to exclude heuristically paired rows.
    pairing_method: Mapped[str | None] = mapped_column(String(16))


class LinkCheck(Base):
    """One visit to one URL at one moment, recorded as raw signals.

    This is the takedown study's measuring instrument, so what it
    stores is deliberately not a verdict. Whether a video counts as
    removed depends on marker phrases that change with the platform's
    interface and on distinctions -- deleted by the author, deleted by
    the platform, set to private, account banned, restricted by region
    -- that one response often cannot separate. Storing `alive: false`
    would bake today's reading of those signals into the data, and a
    later correction could not be applied to videos that are already
    gone.

    So each row keeps what the server actually returned, and
    `app/recheck.py` classifies on read. Reclassifying the whole
    history is then a code change, not a new collection round.
    """

    __tablename__ = "link_checks"
    __table_args__ = (
        Index("ix_check_video_time", "video_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)

    #: Which page was visited: "video" or "author". An author check is
    #: what separates a banned or deleted account from a single removed
    #: video, so it is a first-class row rather than a flag.
    target_kind: Mapped[str] = mapped_column(String(16), default="video")

    video_id: Mapped[str | None] = mapped_column(String(128), index=True)
    author_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(512))

    #: When the visit actually happened, not when it was due. A manual
    #: schedule slips, and the gap between consecutive checks is the
    #: precision of every disappearance time derived from them.
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    http_status: Mapped[int | None] = mapped_column(Integer)
    #: Where the request ended up. A redirect to a login wall or to the
    #: site root is itself a signal, and a different one from a 404.
    final_url: Mapped[str | None] = mapped_column(String(512))
    #: The page title, which is where both platforms put their
    #: "unavailable" wording.
    page_title: Mapped[str | None] = mapped_column(String(512))
    #: A bounded slice of the response, kept so a corrected marker list
    #: can be applied to checks already recorded.
    excerpt: Mapped[str | None] = mapped_column(Text)
    #: Marker names that matched, comma-separated. Raw evidence, not a
    #: conclusion.
    markers: Mapped[str | None] = mapped_column(String(255))
    body_bytes: Mapped[int | None] = mapped_column(Integer)
    #: Exception class name when the request never completed. A network
    #: failure is not a takedown and must never be counted as one.
    error: Mapped[str | None] = mapped_column(String(128))


class AuthorIdentity(Base):
    """An account's stable id, learned from its profile page.

    Douyin renders `@昵称` beside a video and keeps the 抖音号 -- the
    identifier that does not change and is not shared -- one tap away
    on the profile. A nickname is what a study can collect cheaply; the
    抖音号 is what lets an author still be found months later, when
    recruitment actually happens.

    Kept per author rather than per video, because that is what it is:
    one visit answers it for every video that account ever appears in,
    and revisiting would cost collection time for an answer already
    held.
    """

    __tablename__ = "author_identities"
    __table_args__ = (
        UniqueConstraint("platform", "author_name", name="uq_author_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    #: The display name as the feed rendered it, which is the only key
    #: available at the moment a post is captured.
    author_name: Mapped[str] = mapped_column(String(255), index=True)
    #: The 抖音号, read off the profile.
    author_handle: Mapped[str] = mapped_column(String(255), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WebVideo(Base):
    """What the video's own web page says, fetched from a computer.

    The phone reads a feed: it sees what is on screen for a second or
    two, at whatever moment the loop looked, and its author, caption
    and counts have to be stitched to a link afterwards by inference.
    Every mis-association in this study so far came from that stitch.

    A page fetched from the video's own URL needs no stitch. The id is
    in the address, so everything parsed out of the response belongs
    to it by construction. This table is therefore the authority for
    these fields, and the screen readings become corroboration.

    Kept separate from the post tables rather than overwriting them:
    the two are different observations -- one of what a viewer saw in
    the app, one of what the page served to a fetch -- and a study
    that measures removals should be able to show both.
    """

    __tablename__ = "web_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True, default="douyin")
    video_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    #: The account's opaque id, which is what a profile URL is keyed
    #: on. The 抖音号 is not: it is a display identifier the owner can
    #: change, and it is not in the address of anything.
    sec_uid: Mapped[str | None] = mapped_column(String(255), index=True)
    author_name: Mapped[str | None] = mapped_column(String(255))
    #: The 抖音号, when the video page carries it. It usually does not
    #: -- see `web_authors`.
    author_handle: Mapped[str | None] = mapped_column(String(255), index=True)

    caption: Mapped[str | None] = mapped_column(Text)
    posted_on: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    share_count: Mapped[int | None] = mapped_column(Integer)
    collect_count: Mapped[int | None] = mapped_column(Integer)

    #: HTTP status of the fetch, and the class name of whatever went
    #: wrong instead. A page that could not be read is recorded as
    #: such rather than left indistinguishable from one never tried.
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(255))
    #: How the fields were found: the name of the strategy that
    #: matched. A row parsed by a fallback is worth less than one read
    #: out of the page's own data, and the difference should be
    #: visible without re-fetching.
    parsed_by: Mapped[str | None] = mapped_column(String(32))

    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True, default=_utcnow)


class WebAuthor(Base):
    """What an author's profile page says, fetched from a computer.

    The 抖音号 lives here and nowhere else: it is not in a video's
    address and the feed does not render it. One visit answers it for
    every video that account appears in, which is why this is keyed on
    the account rather than stored per video.
    """

    __tablename__ = "web_authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True, default="douyin")
    sec_uid: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    #: The 抖音号.
    author_handle: Mapped[str | None] = mapped_column(String(255), index=True)
    author_name: Mapped[str | None] = mapped_column(String(255))
    signature: Mapped[str | None] = mapped_column(Text)
    #: Douyin shows a coarse location on every profile. Recorded
    #: because it is on the page, not because the study needs it --
    #: and it is a personal detail, so it stays out of exports unless
    #: a written reason says otherwise.
    ip_location: Mapped[str | None] = mapped_column(String(64))

    follower_count: Mapped[int | None] = mapped_column(Integer)
    following_count: Mapped[int | None] = mapped_column(Integer)
    total_favorited: Mapped[int | None] = mapped_column(Integer)
    video_count: Mapped[int | None] = mapped_column(Integer)

    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(255))
    parsed_by: Mapped[str | None] = mapped_column(String(32))

    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True, default=_utcnow)
