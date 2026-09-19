"""Turn a copied short link into a video id.

Douyin's "copy link" yields `https://v.douyin.com/XXXX/` and TikTok's
yields `vm.tiktok.com/XXXX`. Neither contains the video id; both redirect
to a canonical URL that does. Following that redirect is the last step
between a link the operator copied and a citable, re-checkable URL.

This runs wherever the researcher runs it -- a laptop, a server -- and is
unrelated to the phone: it uses no account, no session, and touches
nothing the recommender can observe.

The HTTP call is injected so the logic is testable without the network,
and so a caller can substitute a client with its own retry, proxy or
rate-limit policy.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .links import extract
from .models import SharedLink
from .pairing import backfill_author_handles, pair_shared_link
from .parsers import PLATFORM_TABLES
from .platforms import family_for_platform

#: A desktop browser string. Both platforms serve redirects to anything,
#: but a default urllib agent is refused often enough to be worth it.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

#: Follower signature: given a URL, return the URL it ends up at.
Follower = Callable[[str], str]

#: Progress signature: link number, total, and what became of it.
Progress = Callable[[int, int, str], None]


#: Consecutive landings on an id another link already holds before the
#: pass gives up. Douyin answers a rate limit by redirecting every
#: request to the same page rather than by refusing it, so a repeated
#: id is the only signal that the redirects have stopped meaning
#: anything -- and one bad pass wrote 130 rows the same id.
COLLISION_LIMIT = 3


@dataclass
class ResolveReport:
    attempted: int = 0
    resolved: int = 0
    paired: int = 0
    failed: int = 0
    #: True when the pass stopped early on repeated ids.
    rate_limited: bool = False

    def __str__(self) -> str:
        limited = ", stopped: rate limited" if self.rate_limited else ""
        return (
            f"attempted {self.attempted}, resolved {self.resolved}, "
            f"paired {self.paired}, failed {self.failed}{limited}"
        )


def follow_redirect(url: str, timeout: float = 15.0) -> str:
    """Return the URL a short link lands on."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl()


def pending_links(session: Session) -> list[SharedLink]:
    """Links that were stored without a video id."""
    return list(
        session.scalars(
            select(SharedLink)
            .where(SharedLink.video_id.is_(None))
            .order_by(SharedLink.shared_at)
        )
    )


def resolve_pending(
    session: Session,
    follower: Follower = follow_redirect,
    links: Iterable[SharedLink] | None = None,
    pause_seconds: float = 2.0,
    on_progress: Progress | None = None,
) -> ResolveReport:
    """Resolve unresolved links, then pair each to its captured post.

    A pause between requests is the default on purpose: this walks a
    list of links one at a time against someone else's servers, and a
    study that gets itself rate-limited halfway through collection has
    lost data it cannot go back for. That makes a run of a few hundred
    links minutes long, so `on_progress` is called as each one is
    settled -- a run with no output is indistinguishable from a hang.

    Each resolved link is committed on its own, so stopping partway
    keeps everything done so far and a re-run picks up the rest.
    """
    report = ResolveReport()
    targets = list(links) if links is not None else pending_links(session)

    total = len(targets)
    collisions = 0

    def note(index: int, outcome: str) -> None:
        if on_progress:
            on_progress(index + 1, total, outcome)

    for index, link in enumerate(targets):
        source = link.canonical_url or extract(link.raw_text).raw_url
        if not source:
            report.failed += 1
            note(index, "no link in this row")
            continue

        report.attempted += 1
        if index and pause_seconds:
            time.sleep(pause_seconds)

        try:
            final_url = follower(source)
        except (urllib.error.URLError, OSError, ValueError):
            # A link that cannot be followed now may resolve later: the
            # row is left pending rather than marked bad.
            report.failed += 1
            note(index, "could not be followed")
            continue

        parsed = extract(final_url)
        if not parsed.video_id:
            report.failed += 1
            note(index, f"no video id in the page it landed on: {final_url}")
            continue

        if _already_held(session, link, parsed.video_id):
            # Every share link names a different post, so the same id
            # twice means the redirect stopped tracking the link. Not
            # a bad row: a bad answer, and the rows after it would get
            # the same one.
            report.failed += 1
            collisions += 1
            note(index, f"{parsed.video_id} is already another link's -- not stored")
            if collisions >= COLLISION_LIMIT:
                report.rate_limited = True
                note(index, "stopping: the redirects have stopped naming the post")
                break
            continue
        collisions = 0

        link.video_id = parsed.video_id
        link.canonical_url = parsed.canonical_url or final_url
        if parsed.author_handle and not link.author_handle:
            link.author_handle = parsed.author_handle
        session.commit()
        report.resolved += 1

        paired = pair_shared_link(session, link) is not None
        if paired:
            report.paired += 1
        note(index, parsed.video_id + (" (paired)" if paired else ""))

    return report


def _already_held(session: Session, link: SharedLink, video_id: str) -> bool:
    """Whether some other link already claims this id."""
    held = session.scalar(
        select(func.count())
        .select_from(SharedLink)
        .where(SharedLink.video_id == video_id, SharedLink.id != link.id)
    )
    return bool(held)


def unresolve_duplicates(session: Session) -> int:
    """Undo ids a fallback page handed out, and return how many.

    Repair for a pass that ran before [COLLISION_LIMIT] existed: 214
    links holding 47 ids, one of them 130 times. The rows are not
    deleted -- the copied text is the collected observation and is
    still good -- they go back to pending and resolve again, slower.

    Two links can legitimately name one video, on two different days.
    So this is a command someone runs after seeing a count like the
    one above, never something a resolve pass decides on its own.
    """
    duplicated = [
        video_id
        for video_id, _ in session.execute(
            select(SharedLink.video_id, func.count())
            .where(SharedLink.video_id.isnot(None))
            .group_by(SharedLink.video_id)
            .having(func.count() > 1)
        )
    ]
    if not duplicated:
        return 0

    links = list(
        session.scalars(select(SharedLink).where(SharedLink.video_id.in_(duplicated)))
    )
    for link in links:
        _unresolve(session, link)
    session.commit()
    return len(links)


def _unresolve(session: Session, link: SharedLink) -> None:
    """Return one link to pending, and take the id off its post."""
    if link.matched_capture_id is not None:
        family = family_for_platform(link.platform) or link.platform or ""
        registered = PLATFORM_TABLES.get(family)
        if registered is not None:
            model, _ = registered
            posts = session.scalars(
                select(model).where(model.capture_event_id == link.matched_capture_id)
            )
            for post in posts:
                if post.video_id == link.video_id:
                    post.video_id = None
                    post.video_url = None
    link.matched_capture_id = None
    link.pairing_method = None
    link.video_id = None
    link.canonical_url = None


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import sys

    from .db import SessionLocal, init_db

    def show(done: int, total: int, outcome: str) -> None:
        print(f"[{done}/{total}] {outcome}", flush=True)

    init_db()
    with SessionLocal() as session:
        if "--repair" in sys.argv:
            undone = unresolve_duplicates(session)
            print(f"returned {undone} link(s) to pending")
        print(resolve_pending(session, on_progress=show))
        # Posts paired before handles were adopted still have an empty
        # one; this is where that gets repaired, so re-running the
        # command is all an existing database needs.
        repaired = backfill_author_handles(session)
        if repaired:
            print(f"filled in {repaired} missing @handle(s)")


if __name__ == "__main__":  # pragma: no cover
    main()
