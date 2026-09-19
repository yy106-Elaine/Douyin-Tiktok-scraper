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

from sqlalchemy import select
from sqlalchemy.orm import Session

from .links import extract
from .models import SharedLink
from .pairing import backfill_author_handles, pair_shared_link

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


@dataclass
class ResolveReport:
    attempted: int = 0
    resolved: int = 0
    paired: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"attempted {self.attempted}, resolved {self.resolved}, "
            f"paired {self.paired}, failed {self.failed}"
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
    pause_seconds: float = 1.0,
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


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    def show(done: int, total: int, outcome: str) -> None:
        print(f"[{done}/{total}] {outcome}", flush=True)

    init_db()
    with SessionLocal() as session:
        print(resolve_pending(session, on_progress=show))
        # Posts paired before handles were adopted still have an empty
        # one; this is where that gets repaired, so re-running the
        # command is all an existing database needs.
        repaired = backfill_author_handles(session)
        if repaired:
            print(f"filled in {repaired} missing @handle(s)")


if __name__ == "__main__":  # pragma: no cover
    main()
