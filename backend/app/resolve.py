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


@dataclass
class ResolveReport:
    attempted: int = 0
    resolved: int = 0
    paired: int = 0
    failed: int = 0
    #: Of the resolved, how many were an address already followed.
    #: Worth printing: it is the size of the re-copying, which is a
    #: property of the collection run rather than of the corpus.
    repeated: int = 0

    def __str__(self) -> str:
        again = f", {self.repeated} already known" if self.repeated else ""
        return (
            f"attempted {self.attempted}, resolved {self.resolved}{again}, "
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

    Many links landing on one id is ordinary here and is not guarded
    against. When a day's search results run out the loop keeps
    copying whatever is on screen, so one video collected 130 links
    in a single run -- 晒月亮, `shares=3,629`, the same post the run
    log shows it spinning on. A guard that read a repeated id as a
    rate-limit fallback page refused those, and then blocked every
    pass behind them: the queue is walked in the same order each
    time, so a refusal at the head is a refusal forever.
    """
    report = ResolveReport()
    targets = list(links) if links is not None else pending_links(session)

    # What each short link already resolved to, so the same address is
    # never followed twice. Douyin cannot be told to skip videos
    # already seen, so a run re-copies them; and when the day's results
    # run out the loop keeps copying whatever is still on screen -- one
    # video produced 130 links in a single run. Those are the same
    # address, character for character, so this is an exact match and
    # not a guess about which links are "the same video".
    #
    # It saves the pause as well as the request: 130 links at two
    # seconds each is four minutes spent asking Douyin the same
    # question, which is both slow and the kind of thing that gets a
    # study rate-limited out of data it cannot go back for.
    # Keyed on the *short* address, read back out of the raw text --
    # not on `canonical_url`, which resolving overwrites with the long
    # form. Keyed on the long one this matched nothing, which is a
    # silent no-op rather than a wrong answer, and exactly the kind of
    # thing a test has to hold down.
    known: dict[str, tuple[str, str | None]] = {}
    for raw_text, video_id, canonical in session.execute(
        select(SharedLink.raw_text, SharedLink.video_id, SharedLink.canonical_url)
        .where(SharedLink.video_id.isnot(None))
    ):
        address = extract(raw_text or "").raw_url
        if address and video_id:
            known.setdefault(address, (video_id, canonical))

    total = len(targets)

    def note(index: int, outcome: str) -> None:
        if on_progress:
            on_progress(index + 1, total, outcome)

    for index, link in enumerate(targets):
        # The short address, which is what `known` is keyed on, with
        # the canonical URL as the fallback for a row that has one
        # and no readable raw text.
        source = extract(link.raw_text or "").raw_url or link.canonical_url
        if not source:
            report.failed += 1
            note(index, "no link in this row")
            continue

        report.attempted += 1

        seen = known.get(source)
        if seen is not None:
            # Already followed in this run or an earlier one. Recorded
            # the same way a fresh follow would record it, so a
            # re-copied video is one video with several sightings
            # rather than a link left pending for ever.
            link.video_id, link.canonical_url = seen[0], seen[1] or source
            session.commit()
            report.resolved += 1
            report.repeated += 1
            if pair_shared_link(session, link) is not None:
                report.paired += 1
            note(index, f"{seen[0]} (already known)")
            continue

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
        known[source] = (parsed.video_id, link.canonical_url)
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
        # A link resolved before its capture arrived stayed unpaired
        # for good; both halves are usually here by now.
        # Retrying is held back until the device names the post the
        # share sheet was opened on rather than the last one it read.
        # See pair_unpaired.
        # Posts paired before handles were adopted still have an empty
        # one; this is where that gets repaired, so re-running the
        # command is all an existing database needs.
        repaired = backfill_author_handles(session)
        if repaired:
            print(f"filled in {repaired} missing @handle(s)")


if __name__ == "__main__":  # pragma: no cover
    main()
