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
         survives_kill: bool = False,
         age: str | None = None) -> subprocess.CompletedProcess:
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
        # The guard now reads a pid off this, not just an exit code.
        "    *app*)\n"
        + ("      echo 4242\n      exit 0 ;;\n" if python
           else "      exit 1 ;;\n")
        + "  esac\n"
        "done\n"
        "exit 1\n",
        encoding="utf-8",
    )
    # `ps -o etime=` for the pretend driver. BSD prints DD-HH:MM:SS
    # once a process is over a day old, and that dash is the signal
    # the guard reads.
    (bin_dir / "ps").write_text(
        "#!/bin/bash\n"
        f"cat {tmp_path}/age 2>/dev/null || echo '  04:11'\n",
        encoding="utf-8",
    )
    (bin_dir / "ps").chmod(0o755)
    (bin_dir / "pkill").write_text(
        f"#!/bin/bash\ntouch {tmp_path}/killed\nexit 0\n", encoding="utf-8")
    for name in ("pgrep", "pkill"):
        (bin_dir / name).chmod(0o755)

    if survives_kill:
        (tmp_path / "stubborn").touch()
    if age is not None:
        (tmp_path / "age").write_text(age + "\n", encoding="utf-8")

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


def _helper(name: str) -> str:
    """One shell function, lifted out of daily.sh."""
    text = SCRIPT.read_text(encoding="utf-8")
    found = re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.S | re.M)
    assert found, f"{name} is not in daily.sh any more"
    return found.group(0)


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_progress_is_read_off_the_passes_own_count(tmp_path) -> None:
    """A four-hour silence looks exactly like a run that has hung.

    The parallel passes write only to their own files, so the log a
    person watches says nothing until they finish -- and twice that
    has been read as a stall. The heartbeat reports what the passes
    themselves print, rather than keeping a second count here that
    could disagree with them.
    """
    busy = tmp_path / "video.log"
    busy.write_text("[1/316] a\n[12/316] b\n", encoding="utf-8")
    fresh = tmp_path / "note.log"
    fresh.write_text("", encoding="utf-8")

    script = tmp_path / "hb.sh"
    script.write_text(
        "#!/bin/bash\n" + _helper("furthest")
        + f'\nfurthest {busy} "video"; echo\n'
        + f'furthest {fresh} "图文"; echo\n'
        + f'furthest {tmp_path}/never-written.log "gone"; echo\n',
        encoding="utf-8",
    )
    done = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    lines = done.stdout.strip().splitlines()

    assert lines[0] == "video [12/316]"
    # Started but nothing read yet, and a log that does not exist at
    # all, both say the same honest thing rather than "0".
    assert lines[1] == "图文 starting"
    assert lines[2] == "gone starting"


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_the_heartbeat_does_not_reach_the_phone_page() -> None:
    """The phone page answers "did it run, and did anything break?".

    Forty-eight progress lines are not that, and the page shows the
    last forty lines of the log -- so an unfiltered heartbeat would
    push the step results off it entirely.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    page = re.search(r'grep -E "(\^\[0-9.*?)" \\\n\s+"\$LOG"', text)
    assert page, "the status page's grep has moved"
    # The heartbeat lines are `   ... `, which the page's anchors
    # (`-- `, `   ok`, `   FAILED`, `   STOPPED`) do not admit.
    assert "..." not in page.group(1)


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_the_freed_browser_goes_to_the_other_half_of_the_notes() -> None:
    """304 videos take twenty minutes; 1,384 图文 take hours.

    The video browser used to sit idle for the rest of the run. Now
    the 图文 list is halved from the start and the second half opens
    in the video profile the moment it is free -- two browsers
    throughout, never three, because the same account on more than
    two is what a stolen account looks like.
    """
    text = SCRIPT.read_text(encoding="utf-8")

    # The launch lines, not the comments that mention them.
    launches = [
        line.strip() for line in text.splitlines()
        if "--shard" in line and not line.lstrip().startswith("#")
    ]
    assert [line.split(" --pause")[0] for line in launches] == [
        "--shard 1/2", "--shard 2/2"]

    # The second half takes over the video profile, not a third one.
    second = text.index("        --shard 2/2")
    opened = text.rindex('--profile "$PROFILE"', 0, second)
    assert second - opened < 120
    # And only once the video pass has actually gone.
    assert 'if [[ -z "$pid_c" ]] && ! kill -0 "$pid_a" 2>/dev/null; then' in text


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_a_working_run_and_a_wedged_one_must_not_read_the_same() -> None:
    """Standing down every morning for Tuesday's run is a week of nothing.

    The guard defers to a live `app.*` process, which is right: a
    page read is a database write and a slow run is not a finished
    one, so nothing here kills it. But "a run is using it" was all
    the log said, and a run that wedged yesterday looks exactly like
    one that started an hour ago. The pid and the age are what tell
    them apart, and the judgement stays with the person.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        busy = _run(Path(tmp), browser=True, python=True, age="  04:11")
    assert "STOOD_DOWN" in busy.stdout
    assert "held by pid 4242, running for 04:11" in busy.stdout
    assert "OVER A DAY OLD" not in busy.stdout

    with tempfile.TemporaryDirectory() as tmp:
        # BSD `ps` prints DD-HH:MM:SS once a process is over a day old.
        wedged = _run(Path(tmp), browser=True, python=True, age="1-03:22:14")
    assert "STOOD_DOWN" in wedged.stdout
    assert "OVER A DAY OLD" in wedged.stdout
    assert "kill 4242" in wedged.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="daily.sh is not here")
def test_two_workers_on_one_endpoint_are_paced() -> None:
    """Splitting 图文 in two doubled the request rate and broke the run.

    One worker at no pause read 1,396 pages with 45 unreadable. The
    first run with two workers, also at no pause, read 470 of 1,501
    and timed out on the rest -- median 21.8s against 5.3s the day
    before. The site had stopped returning the record.

    So both shards carry a pause. Halving the wall time is not worth
    buying back in pages that answer nothing, and a page that
    answers nothing is not a free retry: it is a check that spent a
    request and learnt nothing.
    """
    text = SCRIPT.read_text(encoding="utf-8")

    launches = [
        line.strip() for line in text.splitlines()
        if "--shard" in line and not line.lstrip().startswith("#")
    ]
    assert launches == [
        '--shard 1/2 --pause "$SHARD_PAUSE" \\',
        '--shard 2/2 --pause "$SHARD_PAUSE" \\',
    ]
    assert 'SHARD_PAUSE="${SHARD_PAUSE:-2}"' in text
