"""Where in a pass the unreadable pages sit.

    ./.venv/bin/python -m app.logshape logs/2026-10-13-note.log
    ./.venv/bin/python -m app.logshape logs/*.log

Scattered or clustered, and nothing else. It answers one question,
and the question is worth a module because five measurements and
four wrong explanations have gone past without anybody asking it.

A pass that loses its session mid-way goes on walking the list:
every page after that point loads a shell, carries no record, and is
filed as "read, nothing on the page". So a lost session does not
look like a crash. It looks like an unreadable *rate* -- 20%, 39%,
79% -- and the rate is really a position: 79% means it broke early
and 20% means it broke late. Short runs look clean because they
finish first, which is exactly what the two 26-page samples did.

If instead unreadability belongs to the posts -- a note whose author
is gone, a kind of post whose record never reaches a watched
endpoint -- the failures fall where those posts happen to sit in the
list, which is all over it.

The two shapes do not resemble each other, and every log already
written holds the answer. Read-only; it opens nothing and fetches
nothing.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

#: `[12/345] ...` -- what every pass prints per page.
_LINE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")
_UNREADABLE = "nothing readable"


@dataclass
class Shape:
    """One log, as a position rather than a rate."""

    name: str
    pages: int = 0
    total: int = 0
    unreadable: int = 0
    #: 1-based index of the first unreadable page.
    first_bad: int | None = None
    #: Length of the unbroken run of unreadable pages at the end.
    tail: int = 0
    #: Pages read after `first_bad` that were fine. The number that
    #: separates the two stories: a session that ended cannot be
    #: followed by a page that read.
    good_after_first_bad: int = 0

    @property
    def rate(self) -> float:
        return self.unreadable / self.pages if self.pages else 0.0

    @property
    def verdict(self) -> str:
        if not self.unreadable:
            return "no unreadable pages"
        if self.tail >= 5 and self.good_after_first_bad == 0:
            return (
                f"broke at page {self.first_bad} and never recovered "
                f"({self.tail} unreadable to the end)"
            )
        if self.tail >= 5 and self.good_after_first_bad <= self.pages // 20:
            return (
                f"mostly broken from page {self.first_bad} on, with "
                f"{self.good_after_first_bad} page(s) still reading after it"
            )
        return (
            f"scattered: {self.good_after_first_bad} page(s) read fine after "
            f"the first failure at page {self.first_bad}"
        )


def shape_of(text: str, name: str = "") -> Shape:
    seen: list[tuple[int, bool]] = []
    total = 0
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if not match:
            continue
        index = int(match.group(1))
        total = int(match.group(2))
        seen.append((index, _UNREADABLE in match.group(3)))

    found = Shape(name=name, pages=len(seen), total=total)
    if not seen:
        return found

    found.unreadable = sum(1 for _, bad in seen if bad)
    for index, bad in seen:
        if bad:
            found.first_bad = index
            break

    tail = 0
    for _, bad in reversed(seen):
        if not bad:
            break
        tail += 1
    found.tail = tail

    if found.first_bad is not None:
        found.good_after_first_bad = sum(
            1 for index, bad in seen if index > found.first_bad and not bad
        )
    return found


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.logs:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as problem:
            print(f"{path}: {problem}")
            continue
        found = shape_of(text, path.name)
        if not found.pages:
            print(f"{path.name}: no [n/total] lines")
            continue
        print(
            f"{found.name}: {found.pages} page(s), "
            f"{found.unreadable} unreadable ({found.rate:.0%})"
        )
        print(f"  {found.verdict}")


if __name__ == "__main__":  # pragma: no cover
    main()
