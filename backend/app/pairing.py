"""Pair an actively shared link with a passively captured post.

The accessibility stream never sees a video id, and the share sheet
never sees the engagement counts. Each half is useless alone, so we
join them after the fact: a link shared at time T is matched against
the same participant's captures of the same platform within a window
around T, preferring the same author and then the nearest in time.

This is a heuristic. `docs/METHODOLOGY.md` states the failure modes
that belong in a write-up.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .links import canonical_url_for
from .models import SharedLink
from .parsers import PLATFORM_TABLES
from .platforms import family_for_platform


def pair_shared_link(session: Session, link: SharedLink) -> int | None:
    """Attach `link`'s video id to the best matching post. Returns its id."""
    if not link.video_id or not link.platform:
        return None

    family = family_for_platform(link.platform) or link.platform
    registered = PLATFORM_TABLES.get(family)
    if registered is None:
        return None
    model, _ = registered

    window = timedelta(seconds=settings.pairing_window_seconds)
    candidates = session.scalars(
        select(model).where(
            model.participant_id == link.participant_id,
            model.video_id.is_(None),
            model.captured_at >= link.shared_at - window,
            model.captured_at <= link.shared_at + window,
        )
    ).all()

    if not candidates:
        return None

    best = min(candidates, key=lambda post: _distance(post, link))

    # An author mismatch means we matched on time alone; that is weaker
    # than no match at all, so refuse it.
    if link.author_handle and best.author_handle:
        if best.author_handle.lstrip("@").lower() != link.author_handle.lstrip("@").lower():
            return None

    best.video_id = link.video_id
    best.video_url = link.canonical_url or canonical_url_for(
        family, link.video_id, best.author_handle
    )
    link.matched_capture_id = best.capture_event_id
    session.commit()
    return best.id


def _distance(post, link: SharedLink) -> tuple[int, float]:
    """Sort key: same-author first, then nearest in time."""
    same_author = 0
    if link.author_handle and post.author_handle:
        same = post.author_handle.lstrip("@").lower() == link.author_handle.lstrip("@").lower()
        same_author = 0 if same else 1
    return same_author, abs((post.captured_at - link.shared_at).total_seconds())
