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
    feed: Mapped[str | None] = mapped_column(String(64))

    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    share_count: Mapped[int | None] = mapped_column(Integer)
    save_count: Mapped[int | None] = mapped_column(Integer)

    # True when any count above came from an abbreviated display value
    # ("12.3万" / "74.9K") and is therefore approximate.
    counts_approximate: Mapped[bool] = mapped_column(Boolean, default=False)

    is_ad: Mapped[bool | None] = mapped_column(Boolean)
    is_ai_generated: Mapped[bool | None] = mapped_column(Boolean)

    # Populated only once a shared link has been paired to this post.
    video_id: Mapped[str | None] = mapped_column(String(128), index=True)
    video_url: Mapped[str | None] = mapped_column(String(512))


class DouyinPost(_PostMixin, Base):
    __tablename__ = "douyin_posts"


class TikTokPost(_PostMixin, Base):
    __tablename__ = "tiktok_posts"


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
