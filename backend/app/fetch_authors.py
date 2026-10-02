"""Visit each author's profile and record the 抖音号.

    ./.venv/bin/python -m app.fetch_authors            # what is missing
    ./.venv/bin/python -m app.fetch_authors --apply    # go and get it

The handle is the one field neither the feed nor the video page
reliably gives. Douyin's feed renders a display name, which the owner
shares with anyone else who picked it and can change at will; the
抖音号 is on the profile and nowhere else. It is what finds an account
again months later, and what an interview request is addressed to, so
for a study that follows takedowns it is the field that matters most.

Run `app.fetch_videos` first: it records each video's `sec_uid`, and
that is what a profile URL is keyed on. One visit per account, not
per video -- the answer is a property of the account.

Dry by default; `--apply` fetches, pausing between requests.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import now as utc_now
from .browser import AUTHOR_URL as BROWSER_AUTHOR_URL, DEFAULT_PROFILE, open_browser
from .douyin_page import AUTHOR_URL, author_facts, fetch
from .models import SharedLink, WebAuthor, WebVideo

PAUSE_SECONDS = 2.0

#: Recorded when the profile that answered was somebody else's. Kept
#: as an error rather than silently skipped, so the account stays in
#: the list to be read again rather than looking read.
SERVED_ANOTHER_PROFILE = "served another profile"


def forget_orphans(session: Session) -> int:
    """Drop profiles no post in the corpus points at any more.

    A video page that served a different video handed over that
    video's account, and the profile pass then went and read it:
    Johnny Dear, 4.6 million followers, nothing to do with this
    study. Once the mis-stored row is emptied nothing refers to him,
    and a person who is not in the corpus should not be on file.
    """
    # Pointed at by a post *in the corpus*, not merely by a row. An
    # account whose only posts the topic filter excludes is not a
    # participant in this study, and a profile reading of them is
    # personal data this study has no reason to hold.
    excluded = out_of_corpus_ids(session)
    live = {
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebVideo.sec_uid).where(
                WebVideo.sec_uid.isnot(None),
                WebVideo.video_id.notin_(excluded),
            )
        )
    }
    dropped = 0
    for author in session.scalars(select(WebAuthor)):
        # A deliberate keep is not an orphan. The author of a removed
        # post has no video row pointing at them by construction --
        # the row was cleared when the post went -- and deleting them
        # here undid the whole point of keeping them.
        if author.kept_for_video_id is not None:
            continue
        if author.sec_uid not in live:
            session.delete(author)
            dropped += 1
    if dropped:
        session.commit()
    return dropped


def out_of_corpus_ids(session: Session) -> set[str]:
    """Video ids the topic filter has positively excluded.

    Excluded, not "not known to be included". A profile is personal
    data and dropping one is irreversible, so the rule for leaving an
    account out has to be evidence that its posts are out -- every
    post row for the id out of scope, and no hand-copied link for it.
    An id with no post row at all says nothing either way and is left
    alone.
    """
    from .parsers import PLATFORM_TABLES
    from .views import in_scope_filter

    kept: set[str] = set()
    seen: set[str] = set()
    for platform, (model, _) in PLATFORM_TABLES.items():
        for video_id, keep in session.execute(
            select(model.video_id, in_scope_filter(model, platform)).where(
                model.video_id.isnot(None)
            )
        ):
            seen.add(video_id)
            if keep:
                kept.add(video_id)
    # A link copied by hand is in the corpus by construction: somebody
    # chose that video, one video at a time.
    for (video_id,) in session.execute(
        select(SharedLink.video_id).where(SharedLink.video_id.isnot(None))
    ):
        kept.add(video_id)
    return seen - kept


def wanted(session: Session, refresh: bool = False) -> list[str]:
    """Accounts the corpus points at, with no profile reading yet."""
    excluded = out_of_corpus_ids(session)
    # In scope, not merely read. The video pass visits every page it
    # has a row for, including the ones the topic filter excludes --
    # that visit is the takedown check, and it costs nothing to make.
    # Reading their authors' profiles is a different thing: it stores
    # a nickname, a 抖音号, a signature, a location and a follower
    # count for a person whose post is not in this study. A run came
    # back with 周小闹（纯闹）on it, which is how this was noticed.
    #
    # The same filter the dashboard, the CSV export and the re-check
    # use, so an account follows its posts in and out of the corpus.
    known = [
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebVideo.sec_uid)
            .where(
                WebVideo.sec_uid.isnot(None),
                WebVideo.video_id.notin_(excluded),
            )
            .distinct()
        )
    ]
    if refresh:
        return sorted(set(known))
    # Accounts kept when a post was found gone, which no video row
    # points at any more. These are the authors of removed posts --
    # the ones the study exists to reach -- so they belong in the
    # list whatever happened to the post that found them.
    held = [
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebAuthor.sec_uid).where(WebAuthor.author_handle.is_(None))
        )
    ]
    already = {
        sec_uid
        for (sec_uid,) in session.execute(
            select(WebAuthor.sec_uid).where(
                WebAuthor.error.is_(None),
                WebAuthor.author_handle.isnot(None),
            )
        )
    }
    return sorted((set(known) | set(held)) - already)


def shared_handles(session: Session) -> dict[str, list[str]]:
    """抖音号 that are on file under more than one account.

    One handle belongs to one account, so a handle under two sec_uids
    means at least one of them is wrong -- and, before the profile
    pass checked what it had been served, the wrong ones came in runs:
    one stranger's handle written against nine accounts.
    """
    out: dict[str, list[str]] = {}
    for handle, sec_uid in session.execute(
        select(WebAuthor.author_handle, WebAuthor.sec_uid).where(
            WebAuthor.author_handle.isnot(None)
        )
    ):
        out.setdefault(handle, []).append(sec_uid)
    return {handle: ids for handle, ids in out.items() if len(ids) > 1}


def clear_shared_handles(session: Session) -> int:
    """Empty every account in a shared-handle group, and say how many.

    All of them, not all but one: nothing on file says which account
    the handle really belongs to, and keeping one at random would be
    guessing at the field the interviews are addressed to. They go
    back into the list and are read again, this time with the check
    that the profile is the one that was asked for.
    """
    cleared = 0
    for handle, ids in shared_handles(session).items():
        for row in session.scalars(
            select(WebAuthor).where(WebAuthor.author_handle == handle)
        ):
            row.author_handle = None
            row.author_name = None
            row.signature = None
            row.ip_location = None
            row.error = SERVED_ANOTHER_PROFILE
            cleared += 1
    if cleared:
        session.commit()
    return cleared


def store(session: Session, sec_uid: str, page, facts) -> WebAuthor:
    row = session.scalars(
        select(WebAuthor).where(WebAuthor.sec_uid == sec_uid)
    ).first()
    if row is None:
        row = WebAuthor(sec_uid=sec_uid, platform="douyin")
        session.add(row)

    row.http_status = page.http_status
    row.error = page.error
    row.fetched_at = utc_now()
    if facts is not None:
        row.author_handle = facts.author_handle or row.author_handle
        row.author_name = facts.author_name or row.author_name
        row.signature = facts.signature or row.signature
        row.ip_location = facts.ip_location or row.ip_location
        for field in (
            "follower_count",
            "following_count",
            "total_favorited",
            "video_count",
        ):
            value = getattr(facts, field)
            if value is not None:
                setattr(row, field, value)
        row.parsed_by = facts.parsed_by
    session.commit()
    return row


def anonymous(sec_uid: str):
    """Ask the share host, with no session behind the request."""
    return fetch(AUTHOR_URL.format(sec_uid=sec_uid))


def through(browser, on_wall=None):
    """Read the site's own profile page in a signed-in browser."""

    def read(sec_uid: str):
        seen = browser.read(BROWSER_AUTHOR_URL.format(sec_uid=sec_uid))
        if seen.wall and on_wall is not None:
            on_wall(browser)
            seen = browser.read(BROWSER_AUTHOR_URL.format(sec_uid=sec_uid))
        return seen.fetched

    return read


def run(
    session: Session,
    sec_uids: list[str],
    pause_seconds: float = PAUSE_SECONDS,
    dump: Path | None = None,
    fetcher=anonymous,
    on_progress=None,
) -> dict[str, int]:
    report = {"read": 0, "with_handle": 0, "unreadable": 0, "mismatched": 0}
    total = len(sec_uids)

    for index, sec_uid in enumerate(sec_uids):
        if index and pause_seconds:
            time.sleep(pause_seconds)

        page = fetcher(sec_uid)
        facts = (
            author_facts(page.html or "", page.payloads)
            if (page.html or page.payloads)
            else None
        )

        # The page has to be the one that was asked for.
        #
        # Douyin answers a request for a removed video with the next
        # recommended one, and the video pass has checked the id it
        # got back ever since -- that check is where this study's
        # removals come from. The profile pass had no such check, and
        # the site does the same thing here: a run of 45 accounts came
        # back with one stranger's 抖音号 filed under nine different
        # accounts. A wrong handle is worse than none, because an
        # empty field is visibly empty and a wrong one is not.
        if (
            facts is not None
            and facts.sec_uid
            and facts.sec_uid != sec_uid
        ):
            report["mismatched"] = report.get("mismatched", 0) + 1
            page.error = SERVED_ANOTHER_PROFILE
            store(session, sec_uid, page, None)
            if on_progress:
                on_progress(index + 1, total, "served another profile")
            continue

        if facts is None or facts.is_empty():
            report["unreadable"] += 1
            outcome = page.error or f"HTTP {page.http_status}: nothing readable"
            if dump is not None and page.html:
                dump.mkdir(parents=True, exist_ok=True)
                (dump / f"{sec_uid[:40]}.html").write_text(page.html, encoding="utf-8")
                outcome += " -- page written out"
        else:
            report["read"] += 1
            if facts.author_handle:
                report["with_handle"] += 1
            outcome = f"{facts.author_name or '?'}  抖音号={facts.author_handle or '—'}"

        store(session, sec_uid, page, facts)
        if on_progress:
            on_progress(index + 1, total, outcome)

    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="fetch; otherwise count and stop")
    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "empty every account whose 抖音号 is on file under more than "
            "one account, and stop. One handle belongs to one account, "
            "so a shared one means the site served somebody else's "
            "profile and it was believed. They are read again afterwards"
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N accounts")
    parser.add_argument("--refresh", action="store_true", help="re-read profiles already read")
    parser.add_argument("--pause", type=float, default=PAUSE_SECONDS)
    parser.add_argument("--dump", default="", help="directory for pages that could not be read")
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help=(
            "ask the share host with no session, instead of a signed-in "
            "browser -- lighter, but reads far less"
        ),
    )
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument(
        "--headless",
        action="store_true",
        help="no window; a verification page then cannot be answered",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        if args.repair:
            groups = shared_handles(session)
            cleared = clear_shared_handles(session)
            print(
                f"{len(groups)} 抖音号 were on file under more than one "
                f"account; {cleared} account(s) emptied and queued to be "
                "read again.\nRun  python -m app.fetch_authors --apply"
            )
            for handle, ids in list(groups.items())[:10]:
                print(f"  {handle}: {len(ids)} accounts")
            return

        forgotten = forget_orphans(session)
        if forgotten:
            print(f"forgot {forgotten} profile(s) no video points at any more")
        targets = wanted(session, refresh=args.refresh)
        if args.limit is not None:
            targets = targets[: args.limit]

        if not args.apply:
            print(
                f"{len(targets):,} profile(s) to read. Add --apply to fetch them.\n"
                "Run app.fetch_videos first if this is zero -- the sec_uid "
                "comes from the video pages."
            )
            return

        def show(done: int, total: int, outcome: str) -> None:
            print(f"[{done}/{total}] {outcome}", flush=True)

        if args.anonymous:
            report = run(
                session,
                targets,
                pause_seconds=args.pause,
                dump=Path(args.dump) if args.dump else None,
                fetcher=anonymous,
                on_progress=show,
            )
        else:
            # A signed-in browser, and a stop rather than a retry when
            # the site asks for a person. Hammering a challenge is how
            # a session turns into a block.
            def on_wall(browser) -> None:
                browser.wait_for_person("Douyin is asking to sign in or verify.")

            with open_browser(
                Path(args.profile),
                headless=args.headless,
                pause_seconds=args.pause,
            ) as browser:
                # Check the session once, here, rather than discovering
                # it missing on every page. A run that asks to sign in
                # at each of two hundred videos is a run with no
                # session at all, and saying so once is the useful
                # thing to do.
                browser.read("https://www.douyin.com/", settle_seconds=1.0)
                if not browser.is_signed_in():
                    print(
                        "No saved session in "
                        f"{args.profile}. Sign in once first:\n"
                        "    ./.venv/bin/python -m app.login\n"
                        "Or pass --anonymous to read what the share host "
                        "gives without one."
                    )
                    return

                report = run(
                    session,
                    targets,
                    pause_seconds=0,  # the browser paces itself
                    dump=Path(args.dump) if args.dump else None,
                    fetcher=through(browser, on_wall=None if args.headless else on_wall),
                    on_progress=show,
                )
        print(
            f"read {report['read']} profile(s), {report['with_handle']} with a "
            f"抖音号; {report['unreadable']} unreadable; "
            f"{report.get('mismatched', 0)} served somebody else's profile"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
