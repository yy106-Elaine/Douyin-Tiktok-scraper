"""Who to write to next, in an order that is a decision rather than a habit.

    ./.venv/bin/python -m app.outreach                 # the next 20
    ./.venv/bin/python -m app.outreach --count 50
    ./.venv/bin/python -m app.outreach --mark MDQ4... sent
    ./.venv/bin/python -m app.outreach --mark 热拉xxx replied --note "周四晚"
    ./.venv/bin/python -m app.outreach --status
    ./.venv/bin/python -m app.outreach --csv outreach.csv

`interviews.candidates` ranks accounts by how many of their posts
went, which is the right order for *reading* the list and the wrong
order for *working* it. Written down from the top, the interviews all
come from the most heavily removed accounts, and every quotation in
the thesis then comes from the tail of the distribution. That is not
a sample of anything, and `interviews.stratify_placeholder` already
says so.

The intended frame is stratified by what the posts are *about*, which
needs the content coding, which is not run until the collection
window closes. Waiting for it is not free: accounts are disappearing
while we wait, and an account that goes before it is contacted is a
person this study can never hear from. So this is the interim frame,
built from what is already known on the day:

**outcome** -- does this account still have a post down, or did
everything come back? These are different experiences and the
difference is the study's own finding; recruiting from one of them is
recruiting from half the question.

**volume** -- was it one post, or several? One removal is an
accident you might not even have noticed; several is a pattern you
have an account-level theory about.

Four cells. Within each, a seeded shuffle, and the cells are read
round-robin so that stopping at any point leaves the four roughly
balanced instead of leaving the last one empty. The seed is fixed and
recorded, so the order can be reproduced and reported.

What this is not: a probability sample of Chinese WLW creators. It is
a stratified convenience sample of accounts this study observed
losing a post and could still reach -- and the accounts it could not
reach are counted, because their absence is the heaviest finding on
the list.
"""
from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .interviews import Candidate, candidates
from .models import Outreach

#: Where a contact can be. Ordered roughly as it moves.
STATUSES: tuple[str, ...] = (
    "sent",         # the first message has gone out
    "replied",      # they answered, nothing scheduled yet
    "scheduled",    # a time is agreed
    "interviewed",  # it happened
    "paid",         # the ¥50 is sent
    "declined",     # they said no -- never write again
    "no_reply",     # time has passed; still never write again
    "skip",         # excluded by hand, reason in the note
)

#: Statuses that mean this account is finished with, one way or
#: another. "Finished" includes declining: the whole point of the
#: record is that a no is permanent.
CLOSED: frozenset[str] = frozenset({"declined", "no_reply", "skip", "paid"})


def stratum_of(person: Candidate) -> str:
    """Which of the four cells this account sits in.

    Computed from the candidate rather than stored, so a re-run uses
    today's outcome. The stratum is only frozen at the moment of
    contact, by `mark`, which is the moment it describes.
    """
    outcome = "still-gone" if person.still_gone else "came-back"
    volume = "several" if person.removed > 1 else "one"
    return f"{outcome}/{volume}"


@dataclass
class Queued:
    """One account, ready to be written to."""

    person: Candidate
    stratum: str

    @property
    def handle(self) -> str:
        return self.person.handle or ""

    @property
    def profile_url(self) -> str:
        return self.person.profile_url


def contactable(people: list[Candidate]) -> list[Candidate]:
    """Accounts with a 抖音号 on file.

    Everyone else is unreachable through the platform, which is
    usually because the account itself is gone. They are not dropped
    quietly -- `unreachable()` counts them and the summary says so.
    """
    return [person for person in people if person.reachable]


def unreachable(people: list[Candidate]) -> list[Candidate]:
    return [person for person in people if not person.reachable]


def order(people: list[Candidate], seed: int = 20261007) -> list[Queued]:
    """The contact order: seeded shuffle inside each cell, round-robin across.

    Round-robin rather than cell-after-cell because recruitment stops
    when it stops -- when enough people have said yes, or when the
    term ends. Working the cells in sequence would mean the last cell
    is whatever was left over; interleaving means a run cut short is
    still roughly balanced across the four.
    """
    cells: dict[str, list[Candidate]] = {}
    for person in contactable(people):
        cells.setdefault(stratum_of(person), []).append(person)

    shuffled: dict[str, list[Candidate]] = {}
    for name, members in cells.items():
        # Sorted first: `candidates()` order is stable but the shuffle
        # should not depend on it, or the seed does not mean one thing.
        members = sorted(members, key=lambda c: c.sec_uid)
        # A seed per cell, derived from the run seed, so adding an
        # account to one cell does not reshuffle the others.
        random.Random(f"{seed}:{name}").shuffle(members)
        shuffled[name] = members

    queue: list[Queued] = []
    position = 0
    while any(position < len(members) for members in shuffled.values()):
        for name in sorted(shuffled):
            members = shuffled[name]
            if position < len(members):
                queue.append(Queued(person=members[position], stratum=name))
        position += 1
    return queue


def already(session: Session, platform: str = "douyin") -> dict[str, Outreach]:
    """Every account this study has already written to, by sec_uid."""
    return {
        row.sec_uid: row
        for row in session.scalars(
            select(Outreach).where(Outreach.platform == platform)
        )
    }


def next_to_contact(session: Session, people: list[Candidate], count: int,
                    seed: int = 20261007,
                    platform: str = "douyin") -> list[Queued]:
    """The next `count` accounts not yet written to, in contact order."""
    seen = already(session, platform)
    waiting = [item for item in order(people, seed)
               if item.person.sec_uid not in seen]
    return waiting[:count]


def find(people: list[Candidate], who: str) -> Candidate | None:
    """An account by sec_uid or by 抖音号.

    Both, because the sec_uid is what the database keys on and the
    handle is what a person actually has in front of them after
    sending a message.
    """
    for person in people:
        if person.sec_uid == who or person.handle == who:
            return person
    return None


def mark(session: Session, person: Candidate, status: str,
         note: str | None = None, platform: str = "douyin") -> Outreach:
    """Record where a contact got to, creating the row on first contact.

    The stratum is written on the first contact and never rewritten:
    it records which cell the account was drawn from on the day it
    was approached. Recomputing it later would quietly re-describe a
    past decision with present data -- an account whose post came back
    last week would retroactively have been recruited as a came-back
    case, which is not what happened.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; one of {', '.join(STATUSES)}")

    row = session.scalar(
        select(Outreach).where(
            Outreach.sec_uid == person.sec_uid, Outreach.platform == platform
        )
    )
    if row is None:
        row = Outreach(
            platform=platform,
            sec_uid=person.sec_uid,
            handle=person.handle,
            stratum=stratum_of(person),
            status=status,
        )
        session.add(row)
        # Flushed now, so a second `mark` in the same transaction
        # finds this row instead of inserting a duplicate and failing
        # on the unique constraint at commit time.
        session.flush()
    row.status = status
    if note:
        # Appended, not replaced: the history of a contact is part of
        # what happened to it.
        row.note = f"{row.note}\n{note}" if row.note else note
    if person.handle and not row.handle:
        row.handle = person.handle
    return row


@dataclass
class Progress:
    """Where recruitment has got to overall."""

    contactable: int = 0
    unreachable: int = 0
    written_to: int = 0
    open: int = 0
    closed: int = 0
    by_status: dict[str, int] | None = None
    by_stratum: dict[str, int] | None = None


def progress(session: Session, people: list[Candidate],
             platform: str = "douyin") -> Progress:
    rows = already(session, platform)
    by_status: dict[str, int] = {}
    by_stratum: dict[str, int] = {}
    for row in rows.values():
        by_status[row.status] = by_status.get(row.status, 0) + 1
        key = row.stratum or "unrecorded"
        by_stratum[key] = by_stratum.get(key, 0) + 1
    return Progress(
        contactable=len(contactable(people)),
        unreachable=len(unreachable(people)),
        written_to=len(rows),
        open=sum(1 for row in rows.values() if row.status not in CLOSED),
        closed=sum(1 for row in rows.values() if row.status in CLOSED),
        by_status=by_status,
        by_stratum=by_stratum,
    )


def write_csv(path: Path, queue: list[Queued]) -> None:
    """The queue as a file, for working offline.

    This file holds handles and profile links of real people posting
    queer content. It is written where the repository ignores it and
    it does not belong in a shared folder, an email, or a chat.
    """
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        out = csv.writer(handle)
        out.writerow([
            "order", "stratum", "抖音号", "display name", "profile",
            "removed", "still gone", "came back", "sec_uid",
        ])
        for index, item in enumerate(queue, start=1):
            person = item.person
            out.writerow([
                index, item.stratum, person.handle or "", person.name or "",
                person.profile_url, person.removed, person.still_gone,
                person.came_back, person.sec_uid,
            ])


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .db import SessionLocal, init_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="douyin")
    parser.add_argument("--count", type=int, default=20,
                        help="how many to show (default 20)")
    parser.add_argument("--seed", type=int, default=20261007,
                        help="fixed, so the contact order is reproducible")
    parser.add_argument("--mark", nargs=2, metavar=("WHO", "STATUS"),
                        help="record a contact: sec_uid or 抖音号, then one "
                             f"of {', '.join(STATUSES)}")
    parser.add_argument("--note", default=None,
                        help="with --mark: a line to append")
    parser.add_argument("--status", action="store_true",
                        help="where recruitment has got to")
    parser.add_argument("--csv", default=None, metavar="PATH",
                        help="write the whole remaining queue to a file")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        people = candidates(session, args.platform)

        if args.mark:
            who, status = args.mark
            person = find(people, who)
            if person is None:
                raise SystemExit(f"no account matching {who!r}")
            row = mark(session, person, status, args.note, args.platform)
            session.commit()
            print(f"{person.handle or person.sec_uid}: {row.status}"
                  f"  [{row.stratum}]")
            return

        if args.status:
            state = progress(session, people, args.platform)
            print(f"{state.contactable} contactable account(s); "
                  f"{state.unreachable} unreachable (account itself gone)")
            print(f"{state.written_to} written to — "
                  f"{state.open} open, {state.closed} closed")
            for name, count in sorted((state.by_status or {}).items()):
                print(f"  {name:12} {count}")
            if state.by_stratum:
                print("\nby stratum:")
                for name, count in sorted(state.by_stratum.items()):
                    print(f"  {name:20} {count}")
            return

        queue = next_to_contact(session, people, args.count, args.seed,
                                args.platform)

        if args.csv:
            whole = next_to_contact(session, people, len(people), args.seed,
                                    args.platform)
            path = Path(args.csv)
            write_csv(path, whole)
            print(f"{len(whole)} account(s) written to {path}")
            print("This file names real people. Keep it off shared drives.")
            return

        state = progress(session, people, args.platform)
        print(f"{state.contactable} contactable, {state.written_to} already "
              f"written to; {state.unreachable} unreachable\n")
        for index, item in enumerate(queue, start=1):
            person = item.person
            print(f"{index:3}. {person.handle:<24} {item.stratum:<18} "
                  f"{person.removed} removed, {person.still_gone} still gone, "
                  f"{person.came_back} back")
            print(f"     {person.profile_url}")
        if not queue:
            print("Nobody left in the queue.")
        else:
            print(f"\nAfter writing: --mark <抖音号> sent")


if __name__ == "__main__":  # pragma: no cover
    main()
