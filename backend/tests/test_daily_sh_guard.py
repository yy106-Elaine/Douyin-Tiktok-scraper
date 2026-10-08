"""The gate that decides whether the scheduled Douyin pass stands down.

It got this wrong once, and the cost was a whole day of the study's
main measurement, reported as "finished cleanly". The question it
asks has to be "is a run using this profile", not "is a browser
open" -- an interrupted hand-run leaves Chromium sitting at
about:blank with nothing driving it, and standing down for that is
standing down for wreckage.

Tested by lifting the function out of the script and giving it
stubbed `pgrep`/`pkill` on PATH, because the real ones would answer
about this machine.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "daily.sh"


def _function() -> str:
    """`profile_held_by_a_run`, lifted out of daily.sh."""
    text = SCRIPT.read_text(encoding="utf-8")
    found = re.search(
        r"^profile_held_by_a_run\(\) \{.*?^\}", text, re.S | re.M
    )
    assert found, "profile_held_by_a_run is not in daily.sh any more"
    return found.group(0)


def _run(tmp_path: Path, *, browser: bool, python: bool,
         survives_kill: bool = False) -> subprocess.CompletedProcess:
    """Call the gate with a stubbed world. Returns the process.

    `browser` -- a Chromium holds the profile directory.
    `python` -- a page-reading command is running.
    `survives_kill` -- the browser ignores the kill.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # pgrep is asked two different questions and must answer each on
    # its own: the first argument pattern names the profile path, the
    # second names the Python module.
    (bin_dir / "pgrep").write_text(
        "#!/bin/bash\n"
        "for arg; do\n"
        "  case \"$arg\" in\n"
        "    *user-data-dir*)\n"
        f"      if [[ -f {tmp_path}/killed && ! -f {tmp_path}/stubborn ]]; then\n"
        "        exit 1\n"
        "      fi\n"
        f"      exit {0 if browser else 1} ;;\n"
        "    *app*) "
        f"exit {0 if python else 1} ;;\n"
        "  esac\n"
        "done\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "pkill").write_text(
        f"#!/bin/bash\ntouch {tmp_path}/killed\nexit 0\n", encoding="utf-8")
    for name in ("pgrep", "pkill"):
        (bin_dir / name).chmod(0o755)

    if survives_kill:
        (tmp_path / "stubborn").touch()

    script = tmp_path / "gate.sh"
    script.write_text(
        "#!/bin/bash\n"
        "PROFILE=.browser-profile\n"
        "say() { echo \"$*\"; }\n"
        "sleep() { :; }\n"  # the real one would cost three seconds
        + _function()
        + "\nprofile_held_by_a_run && echo STOOD_DOWN || echo CARRY_ON\n",
        encoding="utf-8",
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env,
        cwd=tmp_path,
    )


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_a_live_hand_run_wins() -> None:
    """A person reading pages in another window must not be interrupted.

    Two runs on one browser profile is a lost run and possibly a lost
    session, which is the one part of this collection that cannot be
    replaced.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        done = _run(Path(tmp), browser=True, python=True)

    assert "STOOD_DOWN" in done.stdout
    assert "killed" not in done.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_a_browser_nobody_is_driving_is_wreckage_not_a_run() -> None:
    """This is the failure that cost a day.

    An interrupted hand-run leaves Chromium at about:blank. The old
    gate saw a browser, called it a hand-run, and stood down -- so no
    Douyin page was read all day, and the log said "finished cleanly".
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        done = _run(Path(tmp), browser=True, python=False)

    assert "CARRY_ON" in done.stdout
    assert "nothing is driving it" in done.stdout
    assert "clearing it" in done.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_a_browser_that_will_not_die_is_still_a_reason_to_stand_down() -> None:
    """Failing to clear it is not a licence to open the same directory.

    Two Chromiums on one user-data-dir is how a signed-in profile
    gets corrupted.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        done = _run(Path(tmp), browser=True, python=False, survives_kill=True)

    assert "STOOD_DOWN" in done.stdout
    assert "could not clear it" in done.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_nothing_holding_it_means_carry_on() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        done = _run(Path(tmp), browser=False, python=False)

    assert "CARRY_ON" in done.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_the_pattern_does_not_catch_the_other_profiles() -> None:
    """`.browser-profile` is a prefix of `.browser-profile-note`.

    Without the trailing space, a TikTok or 图文 run by hand would
    have made the Douyin pass stand down for a profile it was never
    going to touch.
    """
    assert 'user-data-dir=$PWD/$PROFILE "' in _function()


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_a_skipped_douyin_pass_is_not_reported_as_clean() -> None:
    """The day's measurement is missing; the page must not say OK.

    Nothing broke, so the old script printed "finished cleanly" and
    the phone's status page said "OK" -- which is the one thing the
    person reads it to find out, answered wrongly.
    """
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'SKIPPED="${SKIPPED}douyin "' in text
    assert 'echo "DID NOT RUN -- $SKIPPED"' in text
    assert 'say "=== finished, but did not run: $SKIPPED"' in text
    # And the clean line is still reachable only with neither.
    clean = text.index('say "=== finished cleanly"')
    assert text.index('if [[ -n "$SKIPPED" ]]; then', clean - 400) < clean
