"""Unattended rounds: ask again for the accounts a pass left behind.

A pass over two hundred profiles takes most of an hour and nobody
watches it finish, so a second pass that has to be started by hand is
a second pass that does not happen. The accounts worth asking again
are the ones the site answered for with somebody else's profile, or
would not answer for at all.
"""
from app.fetch_authors import repeat


def _falling(counts):
    """A `remaining` that returns a shorter list each time it is read."""
    state = {"i": 0}

    def remaining():
        n = counts[min(state["i"], len(counts) - 1)]
        return [f"sec{k}" for k in range(n)]

    return remaining, state


def test_it_runs_again_while_each_round_still_finds_something():
    counts = [10, 6, 2, 0]
    remaining, state = _falling(counts)

    def one_round(targets):
        state["i"] += 1
        return {"read": len(targets)}

    reports = repeat(one_round, remaining, rounds=5, sleep=lambda s: None)

    assert [r["read"] for r in reports] == [10, 6, 2]


def test_a_round_that_finds_nothing_is_the_last_one():
    """What is left is accounts the site has no profile for.

    Deleted or banned, which is its own finding -- and asking again
    only spends requests against a site that counts them.
    """
    remaining = lambda: ["sec1", "sec2"]
    rounds_run = []

    repeat(
        lambda targets: rounds_run.append(targets) or {},
        remaining,
        rounds=9,
        sleep=lambda s: None,
    )

    assert len(rounds_run) == 1


def test_nothing_wanted_means_no_round_at_all():
    assert repeat(lambda t: {}, lambda: [], rounds=4, sleep=lambda s: None) == []


def test_it_waits_between_rounds_and_not_after_the_last():
    counts = [4, 2, 0]
    remaining, state = _falling(counts)
    slept = []

    def one_round(targets):
        state["i"] += 1
        return {}

    repeat(
        one_round, remaining, rounds=3, round_pause=240.0, sleep=slept.append
    )

    # Two rounds ran; the pause belongs between them, not at the end.
    assert slept == [240.0]


def test_the_rounds_ceiling_holds():
    remaining, state = _falling([100, 90, 80, 70, 60])

    def one_round(targets):
        state["i"] += 1
        return {}

    reports = repeat(one_round, remaining, rounds=2, sleep=lambda s: None)
    assert len(reports) == 2
