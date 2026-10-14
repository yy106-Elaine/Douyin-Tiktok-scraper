"""The morning check: read-only, and it must say so when nothing ran.

A status screen that prints a tidy summary of a night when the pass
never started is worse than no screen, because it is read as "fine".
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "checkup.sh"


def test_it_opens_no_browser_and_writes_nothing() -> None:
    """It is run while a pass is going. Anything that takes the
    profile would stop the pass it was called to look at."""
    text = SCRIPT.read_text(encoding="utf-8")

    # Named in prose (the log names mention them) but never run:
    # what matters is that no line executes one.
    runs = [line for line in text.splitlines()
            if line.strip().startswith("$PY -m")]
    for forbidden in ("app.daily", "app.fetch_videos", "app.fetch_authors",
                      "app.download_videos", "app.resolve"):
        assert all(forbidden not in line for line in runs), forbidden
    assert "--apply" not in text

    # `app.login --check` is named only inside the closing note that
    # explains why it is NOT run here.
    assert all("login" not in line for line in runs)


def test_a_pass_that_did_not_finish_is_called_out() -> None:
    """Every pass ends with a "read N; ..." summary. A log without
    one is a pass that died, and the row has to say that rather than
    quietly showing nothing."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "DID NOT FINISH" in text


def test_it_warns_about_a_browser_nothing_is_driving() -> None:
    """Twice an interrupted run left a Chromium holding the profile,
    the scheduled job stood down for the corpse, and a whole day of
    Douyin went unchecked while the log said it finished cleanly."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "user-data-dir=.*browser-profile" in text
    assert "stand down" in text


def test_every_section_is_numbered_and_in_order() -> None:
    """It is read top to bottom at seven in the morning."""
    text = SCRIPT.read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r'rule "(\d+)\.', text)]
    assert numbers == sorted(numbers)
    assert numbers == list(range(1, len(numbers) + 1))
