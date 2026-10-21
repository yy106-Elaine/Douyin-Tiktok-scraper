"""Which profiles she has already opened, read from the browser's history.

    ./.venv/bin/python -m app.visited > /tmp/seen.txt
    ./.venv/bin/python -m app.report --out takedowns.html --outreach \
        --seen-from /tmp/seen.txt

A profile link she has opened is purple on the contact page, and that
purple is the record of a decision: the account was either written to
or looked at and passed over. Either way it is finished with, and the
list should stop offering it.

The page cannot act on that. `:visited` is unreadable from script in
every browser -- through `getComputedStyle`, through layout timing,
through every trick found since -- because a page that could read it
could read the whole history. So the colour is for her eyes only.

But the history itself is a SQLite file on her own disk, and reading
her own history on her own machine is not the thing that restriction
exists to prevent. This reads it, keeps only `douyin.com/user/...`
addresses, and prints the sec_uid of each.

Copied before it is opened: Chrome holds an exclusive lock on the
file while it is running, so a direct read fails with "database is
locked" whenever the browser is open, which is always. The copy is
read-only and deleted after.

Nothing here leaves the machine and nothing is written to the
history. Only Douyin profile addresses are kept -- the rest of the
history is not read into memory beyond the one query that filters it.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

#: Chrome's default profile on macOS. Firefox and Safari keep theirs
#: elsewhere and in other shapes; this is the browser the contact
#: page is worked in.
CHROME_HISTORY = (
    Path.home() / "Library/Application Support/Google/Chrome"
    / "Default/History"
)

#: The sec_uid sits between `/user/` and the next `?` or `/`.
_PREFIX = "https://www.douyin.com/user/"


def sec_uid_of(url: str) -> str | None:
    """The account id in a Douyin profile address, or None.

    Query strings are common on these links -- the site appends a
    `?from_tab_name=` and more besides -- and an id with a query
    stuck to it matches nothing in the report.
    """
    for prefix in (_PREFIX, _PREFIX.replace("https://www.", "https://")):
        if url.startswith(prefix):
            rest = url[len(prefix):]
            for cut in ("?", "#", "/"):
                rest = rest.split(cut, 1)[0]
            return rest or None
    return None


def visited(history: Path) -> list[str]:
    """Every Douyin profile id in this history file, oldest first.

    The copy is what is opened: Chrome locks the original while it
    runs. `immutable=1` would be wrong here -- the copy may be a
    partial snapshot of a file being written -- so it is opened
    read-only and any corruption surfaces as an error rather than as
    a quietly short list.
    """
    with tempfile.TemporaryDirectory() as work:
        copy = Path(work) / "History"
        shutil.copy2(history, copy)
        found: dict[str, None] = {}
        with sqlite3.connect(f"file:{copy}?mode=ro", uri=True) as db:
            for (url,) in db.execute(
                "select url from urls where url like ? order by last_visit_time",
                (f"{_PREFIX}%",),
            ):
                who = sec_uid_of(url)
                if who:
                    found.setdefault(who, None)
    return list(found)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", default=str(CHROME_HISTORY),
                        help="path to the browser's History file")
    args = parser.parse_args()

    history = Path(args.history).expanduser()
    if not history.exists():
        raise SystemExit(
            f"no history file at {history}\n"
            "If Chrome is not the browser you open the list in, pass "
            "--history. Firefox keeps places.sqlite in its profile "
            "folder and Safari History.db in ~/Library/Safari, and "
            "neither has the same table, so neither is read here."
        )

    found = visited(history)
    for who in found:
        print(who)

    # On stderr so it stays out of the pipe. An empty list reads as
    # "nothing has been opened", which is almost never what happened.
    if not found:
        print(
            f"no douyin.com/user/ addresses in {history}. Either the "
            "list is opened in another browser or another Chrome "
            "profile -- pass --history -- or the history has been "
            "cleared since.",
            file=sys.stderr,
        )


if __name__ == "__main__":  # pragma: no cover
    main()
