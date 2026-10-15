"""The pre-flight check: will the 03:00 run do what today's runs did?

Every line in it is a thing that has gone wrong at least once this
week, which is the only reason any of them are worth a check.
"""
from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tonight.sh"


def test_it_checks_each_fault_that_actually_happened() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    # The image blocking (10-06..10-13): 5-60% of every pass lost.
    assert "--light" in text
    # Two browsers on one account (10-09..10-13): invented removals.
    assert "DOUYIN_PARALLEL" in text
    # filter_detail unread for a month: removals filed as unknown.
    assert "API_FILTERED" in text and "filter_reason" in text
    # A stale page read as current.
    assert "app.report" in text


def test_it_opens_nothing_and_writes_nothing() -> None:
    """It is run before bed, possibly while a pass is going. Taking
    the profile to answer "is the session alive" would stop the thing
    it was called to protect."""
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("--apply", "app.daily", "app.fetch_videos",
                      "app.download_videos"):
        assert f"$PY -m {forbidden}" not in text
    # `app.login --check` appears only in the sentence telling her to
    # run it herself, never as a command this script executes.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("$PY") or stripped.startswith('"$PY"'):
            assert "login" not in stripped


def test_it_exits_nonzero_when_something_needs_fixing() -> None:
    """Called from another script or read in a hurry, the exit code
    has to carry the answer."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert '[[ "$bad" -eq 0 ]]' in text


def test_the_running_pass_check_names_the_commands() -> None:
    """`-m app.` also matches this script's own python and a pytest
    run, and reported a pass in progress on a machine where nothing
    was running."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "app\\.\\(daily" in text
