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
from .models import CaptureEvent, SharedLink
from .parsers import PLATFORM_TABLES
from .platforms import family_for_platform


def pair_shared_link(session: Session, link: SharedLink) -> int | None:
    """Attach `link`'s video id to the matching post. Returns its id."""
    if not link.video_id or not link.platform:
        return None

    family = family_for_platform(link.platform) or link.platform
    registered = PLATFORM_TABLES.get(family)
    if registered is None:
        return None
    model, _ = registered

    exact = _pair_by_fingerprint(session, link, model, family)
    if exact is not None:
        return exact

    if not settings.pairing_window_seconds:
        return None

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

    _attach(session, link, best, family, method="window")
    return best.id


def undo_window_pairings(session: Session) -> int:
    """Take back the ids attached on time alone. See [undo_pairings]."""
    return undo_pairings(session, "window")


def pair_unpaired(session: Session) -> int:
    """Try again for links whose capture had not arrived yet.

    Pairing used to be attempted once, when a link was resolved. The
    phone uploads links and captures on their own schedules and the
    server follows a new link about a minute after it arrives, so a
    link routinely reached its id before the post it was copied from
    reached the server -- and a resolved link is skipped by every
    later pass, so it stayed unpaired for good. One run: eleven links
    resolved, none paired, with the matching fingerprints sitting in
    `capture_events` the whole time.

    Nothing here is new evidence; it is the same exact match, asked
    once more now that both halves are present.

    **Not called anywhere yet.** Running it over the backlog paired
    72 links and put the wrong caption beside the wrong counts,
    because the fingerprint a link carries is the last post the
    device read off the screen -- and the capture buffer settles
    more slowly than the loop copies links, so several links share
    one stale fingerprint. Asking more often multiplies that error
    instead of fixing it. It waits for the device to name the post
    the share sheet was opened on.
    """
    paired = 0
    links = session.scalars(
        select(SharedLink).where(
            SharedLink.video_id.isnot(None),
            SharedLink.matched_capture_id.is_(None),
        )
    ).all()
    for link in links:
        if pair_shared_link(session, link) is not None:
            paired += 1
    return paired


def undo_pairings(session: Session, method: str) -> int:
    """Take back every id attached by one pairing method.

        id ...819109   @handle 晒月亮   name 想吃什么月亮
                       41K / 187 / 3,629   "你最忘不了哪一任 #lwl"

    One video's counts beside another's caption, and nothing on the
    row says so. The assisted loop copies a link about two seconds
    after the post reaches the screen, at a steady cadence, so once
    the ordering slipped by one the nearest-in-time match was wrong
    for every post after it -- wrong in a way that looks orderly.

    This clears `video_id` and `video_url` from the posts those
    pairings wrote to, and unlinks the links. Nothing is deleted: the
    post keeps what it read off the screen, the link keeps its id and
    its share text, and they stand as two rows instead of one row
    that mixes them.
    """
    from .parsers import PLATFORM_TABLES
    from .platforms import family_for_platform

    undone = 0
    links = session.scalars(
        select(SharedLink).where(SharedLink.pairing_method == method)
    ).all()
    for link in links:
        family = family_for_platform(link.platform) or link.platform or ""
        registered = PLATFORM_TABLES.get(family)
        if registered is not None and link.matched_capture_id is not None:
            model, _ = registered
            for post in session.scalars(
                select(model).where(model.capture_event_id == link.matched_capture_id)
            ):
                if post.video_id == link.video_id:
                    post.video_id = None
                    post.video_url = None
        link.matched_capture_id = None
        link.pairing_method = None
        undone += 1

    session.commit()
    return undone


def _pair_by_fingerprint(session: Session, link: SharedLink, model, family: str):
    """Exact pairing: the device harvested this link for a known capture.

    No time window and no author comparison are needed -- the device
    triggered the share from the post itself, so the association is a
    fact rather than an inference.

    Unless two links arrive carrying the same fingerprint, which an
    assisted run produces: the device names the post it last read off
    the screen, and the capture buffer settles more slowly than the
    loop copies links. Several videos then share one stale fingerprint,
    and without the guard below each link overwrote the previous one on
    the same post -- so three links "paired exactly" and one post ended
    up holding whichever id was written last. That is worse than an
    unpaired link: it is a wrong link labelled exact.

    A post that already carries a different id is therefore refused, and
    the caller falls back to window pairing, which says in the data that
    it is a heuristic.
    """
    if not link.fingerprint:
        return None

    post = session.scalars(
        select(model)
        .join(CaptureEvent, CaptureEvent.id == model.capture_event_id)
        .where(
            model.participant_id == link.participant_id,
            CaptureEvent.fingerprint == link.fingerprint,
        )
        .order_by(model.captured_at.desc())
    ).first()
    if post is None:
        return None
    if post.video_id and post.video_id != link.video_id:
        return None

    _attach(session, link, post, family, method="fingerprint")
    return post.id


def _attach(session: Session, link: SharedLink, post, family: str, method: str) -> None:
    post.video_id = link.video_id
    post.video_url = link.canonical_url or canonical_url_for(
        family, link.video_id, post.author_handle
    )
    _adopt_handle(link, post)
    link.matched_capture_id = post.capture_event_id
    link.pairing_method = method
    session.commit()


def _adopt_handle(link: SharedLink, post) -> None:
    """Give the post the `@handle` the resolved link revealed.

    The feed renders a display name, not a handle, so most captures
    have none -- and the handle is the only form that finds the account
    again or reaches its owner. A resolved link's URL contains it, so
    pairing is the moment it becomes known.

    On Douyin the link carries something better: the 抖音号 the device
    read off the author's profile. The column may already hold the
    display name, which was only ever a stand-in for exactly this, so
    that one is replaced. A handle that is neither empty nor the
    display name was observed some other way and is left alone.
    """
    if not link.author_handle:
        return
    handle = link.author_handle.lstrip("@")
    if not post.author_handle or post.author_handle in (post.author_name, handle):
        post.author_handle = handle


def backfill_author_handles(session: Session) -> int:
    """Repair posts paired before handles were adopted. Returns the count.

    Idempotent, and safe to run at any time: it only fills columns that
    are empty. Called by `python -m app.resolve`.
    """
    filled = 0
    for link in session.scalars(
        select(SharedLink).where(
            SharedLink.matched_capture_id.isnot(None),
            SharedLink.author_handle.isnot(None),
        )
    ):
        family = family_for_platform(link.platform) or link.platform
        registered = PLATFORM_TABLES.get(family)
        if registered is None:
            continue
        model, _ = registered
        post = session.scalars(
            select(model).where(
                model.capture_event_id == link.matched_capture_id,
                model.author_handle.is_(None),
            )
        ).first()
        if post is None:
            continue
        _adopt_handle(link, post)
        filled += 1
    if filled:
        session.commit()
    return filled


def _distance(post, link: SharedLink) -> tuple[int, float]:
    """Sort key: same-author first, then nearest in time."""
    same_author = 0
    if link.author_handle and post.author_handle:
        same = post.author_handle.lstrip("@").lower() == link.author_handle.lstrip("@").lower()
        same_author = 0 if same else 1
    return same_author, abs((post.captured_at - link.shared_at).total_seconds())


def record_author_identity(
    session: Session, platform: str, author_name: str, author_handle: str
) -> int:
    """Store an account's stable id and put it on the rows already held.

    Returns how many stored posts it filled in.

    A row whose handle is the nickname is upgraded, because that was
    always a stand-in for this. A row that already carries a different
    stable id is left alone: two accounts can share a nickname, and
    overwriting one account's id with another's on the strength of a
    matching display name would be inventing an association rather
    than observing one.
    """
    from .models import AuthorIdentity

    name = (author_name or "").strip()
    handle = (author_handle or "").strip()
    if not name or not handle:
        return 0

    family = family_for_platform(platform) or platform
    existing = session.scalar(
        select(AuthorIdentity).where(
            AuthorIdentity.platform == family,
            AuthorIdentity.author_name == name,
        )
    )
    if existing is None:
        session.add(
            AuthorIdentity(platform=family, author_name=name, author_handle=handle)
        )
    else:
        existing.author_handle = handle

    filled = 0
    registered = PLATFORM_TABLES.get(family)
    if registered is not None:
        model, _ = registered
        for post in session.scalars(
            select(model).where(model.author_name == name)
        ):
            if post.author_handle in (None, "", name):
                post.author_handle = handle
                filled += 1
    session.commit()
    return filled


def drop_attached_handles(session: Session, platform: str = "douyin") -> int:
    """Forget handles that were attached rather than observed.

        id ...958326   @handle 颜小颜   name moyani

    On Douyin the handle is the 抖音号 and it is only on the author's
    profile. One build read it there and attached it to whichever
    link was nearest in time, which put it on the neighbouring
    author's row as often as the right one. The display name is kept
    -- it was read off the post itself -- and the handle column goes
    empty until a profile is read properly and tied to its post.
    """
    from .parsers import PLATFORM_TABLES

    registered = PLATFORM_TABLES.get(platform)
    if registered is None:
        return 0
    model, _ = registered

    cleared = 0
    for post in session.scalars(select(model).where(model.author_handle.isnot(None))):
        if (post.author_handle or "").lstrip("@").strip() != (
            post.author_name or ""
        ).lstrip("@").strip():
            post.author_handle = None
            cleared += 1
    for link in session.scalars(
        select(SharedLink).where(
            SharedLink.platform == platform, SharedLink.author_handle.isnot(None)
        )
    ):
        link.author_handle = None
        cleared += 1

    session.commit()
    return cleared


def restore_url_handles(session: Session, platform: str = "tiktok") -> int:
    """Put back the handle the link's own address carries.

    The device also reads an `@handle` off the TikTok screen, and it
    used to win over the one in `/@name/video/<id>`. Ingest prefers
    the address now -- see `app/main.py` for why -- and this brings
    the rows stored before that into line, reading the address each
    row already holds, so nothing is re-collected and nothing is
    guessed.

    Expect it to report zero. Every TikTok link checked so far
    already carried the handle its own address gives; the two sources
    have not been seen to disagree. It exists so that the day they do
    is a command rather than a migration, and so the claim "they
    agree" stays checkable rather than remembered.
    """
    from .links import extract

    fixed = 0
    for link in session.scalars(
        select(SharedLink).where(SharedLink.platform == platform)
    ):
        said = extract(link.canonical_url or link.raw_text or "").author_handle
        if said and said != link.author_handle:
            link.author_handle = said
            fixed += 1
    if fixed:
        session.commit()
    return fixed


def main() -> None:  # pragma: no cover - thin CLI wrapper
    """Undo pairings made on time alone. See [undo_window_pairings]."""
    import argparse

    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--undo-time-pairings",
        action="store_true",
        help="unlink every post whose id came from a nearest-in-time match",
    )
    parser.add_argument(
        "--undo-fingerprint-pairings",
        action="store_true",
        help=(
            "unlink every post paired by fingerprint -- the device names "
            "the last post it read, not the one the sheet was opened on"
        ),
    )
    parser.add_argument(
        "--drop-attached-handles",
        action="store_true",
        help="forget Douyin handles attached from a profile visit, not observed",
    )
    parser.add_argument(
        "--restore-url-handles",
        action="store_true",
        help=(
            "put back the @handle each TikTok link's own address carries, "
            "over the one the device read off the screen"
        ),
    )
    args = parser.parse_args()
    if not (
        args.undo_time_pairings
        or args.undo_fingerprint_pairings
        or args.drop_attached_handles
        or args.restore_url_handles
    ):
        parser.error("nothing to do; pass one of the --undo/--drop options")

    init_db()
    with SessionLocal() as session:
        if args.undo_time_pairings:
            print(f"unlinked {undo_window_pairings(session)} time-based pairing(s)")
        if args.undo_fingerprint_pairings:
            print(
                f"unlinked {undo_pairings(session, 'fingerprint')} "
                "fingerprint pairing(s)"
            )
        if args.drop_attached_handles:
            print(f"cleared {drop_attached_handles(session)} attached handle(s)")
        if args.restore_url_handles:
            print(f"corrected {restore_url_handles(session)} handle(s) from the address")


if __name__ == "__main__":  # pragma: no cover
    main()
