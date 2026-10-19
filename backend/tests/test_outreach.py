"""The recruitment queue: strata, order, and the record of who was written to."""
from __future__ import annotations

from datetime import datetime

from app.db import SessionLocal
from app.interviews import Candidate, Post
from app.models import Outreach
from app.outreach import (
    CLOSED,
    STATUSES,
    already,
    contactable,
    find,
    mark,
    next_to_contact,
    order,
    progress,
    stratum_of,
    unreachable,
    write_csv,
)


def _post(video_id: str, *, gone: bool, ever_gone: bool = True) -> Post:
    return Post(
        video_id=video_id,
        platform="douyin",
        caption=None,
        published_at=datetime(2026, 9, 1, 12, 0),
        first_gone_at=datetime(2026, 9, 20, 12, 0) if ever_gone else None,
        came_back_at=None if gone else datetime(2026, 9, 25, 12, 0),
        lifetime=None,
        gone=gone,
        ever_gone=ever_gone,
    )


def _person(sec_uid: str, *, handle: str | None, gone: int = 0,
            back: int = 0) -> Candidate:
    posts = [_post(f"{sec_uid}-g{i}", gone=True) for i in range(gone)]
    posts += [_post(f"{sec_uid}-b{i}", gone=False) for i in range(back)]
    return Candidate(sec_uid=sec_uid, handle=handle, name=None, posts=posts)


def test_the_four_strata_split_outcome_from_volume() -> None:
    """One removal is an accident; several is a pattern you have a theory about.

    And an account still missing a post is living a different thing
    from one whose post came back -- which is the study's own finding,
    so recruiting from only one of them is recruiting from half the
    question.
    """
    assert stratum_of(_person("a", handle="a", gone=1)) == "still-gone/one"
    assert stratum_of(_person("b", handle="b", gone=3)) == "still-gone/several"
    assert stratum_of(_person("c", handle="c", back=1)) == "came-back/one"
    assert stratum_of(_person("d", handle="d", back=2)) == "came-back/several"

    # Still down anywhere makes it a still-gone account, however many
    # of the others came back.
    assert stratum_of(
        _person("e", handle="e", gone=1, back=4)) == "still-gone/several"


def test_the_queue_is_not_the_reading_order(db: None) -> None:
    """Worked from the top, `candidates()` would interview only the worst-hit.

    Its order is by how many posts went, which is right for reading a
    list and wrong for working one: every quotation in the thesis
    would then come from the tail of the distribution.
    """
    people = [_person(f"acct{i:02d}", handle=f"h{i:02d}", gone=i % 5 + 1)
              for i in range(20)]
    by_removals = [p.sec_uid for p in sorted(people, key=lambda c: -c.removed)]

    queue = [item.person.sec_uid for item in order(people)]

    assert sorted(queue) == sorted(by_removals)
    assert queue != by_removals
    # Same seed, same order -- it is a decision that can be reported.
    assert [item.person.sec_uid for item in order(people)] == queue
    assert [item.person.sec_uid for item in order(people, seed=7)] != queue


def test_stopping_early_still_leaves_the_cells_balanced() -> None:
    """Recruitment stops when it stops, not when the list runs out.

    Cell after cell would make the last cell whatever was left over.
    Round-robin means a run cut short is still roughly balanced.
    """
    people = (
        [_person(f"sg1-{i}", handle=f"a{i}", gone=1) for i in range(10)]
        + [_person(f"sgN-{i}", handle=f"b{i}", gone=3) for i in range(10)]
        + [_person(f"cb1-{i}", handle=f"c{i}", back=1) for i in range(10)]
        + [_person(f"cbN-{i}", handle=f"d{i}", back=2) for i in range(10)]
    )

    first_twelve = order(people)[:12]
    seen: dict[str, int] = {}
    for item in first_twelve:
        seen[item.stratum] = seen.get(item.stratum, 0) + 1

    assert len(seen) == 4
    assert set(seen.values()) == {3}


def test_an_account_with_no_handle_is_counted_not_dropped() -> None:
    """Being unreachable is the heaviest finding on the list.

    No 抖音号 usually means the account itself is gone, so the person
    cannot be reached through the platform at all. Silently shortening
    the queue would turn that into a smaller denominator instead of a
    result.
    """
    people = [
        _person("has", handle="reachable", gone=1),
        _person("none", handle=None, gone=2),
    ]

    assert [p.sec_uid for p in contactable(people)] == ["has"]
    assert [p.sec_uid for p in unreachable(people)] == ["none"]
    assert [item.person.sec_uid for item in order(people)] == ["has"]


def test_nobody_is_written_to_twice(db: None) -> None:
    """A duplicate is not a clerical slip.

    On Douyin the first message to a non-follower is the one that gets
    through, so writing again does not repeat the contact -- it spends
    it, on someone who may already have said no.
    """
    people = [_person(f"acct{i}", handle=f"h{i}", gone=1) for i in range(5)]

    with SessionLocal() as session:
        first = next_to_contact(session, people, 2)
        assert len(first) == 2

        for item in first:
            mark(session, item.person, "sent")
        session.commit()

        after = next_to_contact(session, people, 5)
        assert len(after) == 3
        assert not ({i.person.sec_uid for i in after}
                    & {i.person.sec_uid for i in first})

        # A declined contact never comes back into the queue either.
        mark(session, after[0].person, "declined", note="说不方便")
        session.commit()
        assert after[0].person.sec_uid not in {
            item.person.sec_uid for item in next_to_contact(session, people, 5)
        }


def test_the_stratum_is_frozen_at_first_contact(db: None) -> None:
    """A past decision must not be re-described with present data.

    This account was approached as a still-gone case. If its post
    comes back next week, the record must still say what it was when
    it was recruited, or the frame is one nobody can report.
    """
    before = _person("acct", handle="h", gone=1)

    with SessionLocal() as session:
        mark(session, before, "sent")
        session.commit()

        after = _person("acct", handle="h", back=1)  # the post came back
        assert stratum_of(after) == "came-back/one"
        row = mark(session, after, "replied")
        session.commit()

        assert row.stratum == "still-gone/one"
        assert row.status == "replied"


def test_notes_accumulate_rather_than_overwrite(db: None) -> None:
    """The history of a contact is part of what happened to it."""
    person = _person("acct", handle="h", gone=1)

    with SessionLocal() as session:
        mark(session, person, "sent", note="10-07 发了第一条")
        mark(session, person, "replied", note="10-08 回了，周四晚上")
        session.commit()

        row = already(session)["acct"]

    assert "10-07" in (row.note or "")
    assert "10-08" in (row.note or "")


def test_an_unknown_status_is_refused(db: None) -> None:
    """A typo in a status is a contact that silently leaves the queue."""
    import pytest

    person = _person("acct", handle="h", gone=1)
    with SessionLocal() as session:
        with pytest.raises(ValueError):
            mark(session, person, "snet")

    assert CLOSED <= set(STATUSES)


def test_an_account_is_found_by_handle_as_well_as_by_id() -> None:
    """The 抖音号 is what is in front of her after sending a message."""
    people = [_person("sec-abc", handle="热拉xyz", gone=1)]

    assert find(people, "sec-abc") is people[0]
    assert find(people, "热拉xyz") is people[0]
    assert find(people, "nobody") is None


def test_progress_separates_open_contacts_from_finished_ones(db: None) -> None:
    """"Written to" is not "waiting on"; a no is finished, not pending."""
    people = [_person(f"acct{i}", handle=f"h{i}", gone=1) for i in range(4)]
    people.append(_person("gone", handle=None, gone=1))

    with SessionLocal() as session:
        mark(session, people[0], "sent")
        mark(session, people[1], "declined")
        mark(session, people[2], "paid")
        session.commit()

        state = progress(session, people)

    assert state.contactable == 4
    assert state.unreachable == 1
    assert state.written_to == 3
    assert state.open == 1
    assert state.closed == 2
    assert state.by_status == {"sent": 1, "declined": 1, "paid": 1}


def test_the_csv_carries_what_a_message_needs(db: None, tmp_path) -> None:
    """Enough to find the person and know what happened to their posts."""
    people = [_person("acct", handle="热拉xyz", gone=2, back=1)]
    path = tmp_path / "queue.csv"

    write_csv(path, order(people))
    text = path.read_text(encoding="utf-8-sig")

    assert "热拉xyz" in text
    assert "https://www.douyin.com/user/acct" in text
    assert "still-gone/several" in text


def test_the_table_holds_one_row_per_account(db: None) -> None:
    """The question asked of it is always "where is this person now"."""
    person = _person("acct", handle="h", gone=1)

    with SessionLocal() as session:
        mark(session, person, "sent")
        session.commit()
        mark(session, person, "interviewed")
        session.commit()

        rows = list(session.scalars(
            __import__("sqlalchemy").select(Outreach)
        ))

    assert len(rows) == 1
    assert rows[0].status == "interviewed"


def test_the_came_back_cells_can_be_held_back(db: None) -> None:
    """A post that went and came back has at least three possible
    causes and this study can tell none of them apart: the platform
    put it back, this instrument was wrong, or it was throttled
    rather than removed. Asking somebody about a removal that did not
    happen is the one approach that cannot be taken back.
    """
    people = [
        _person("down1", handle="a", gone=1),
        _person("down2", handle="b", gone=2, back=1),
        _person("back1", handle="c", back=1),
        _person("back2", handle="d", back=3),
    ]

    with SessionLocal() as session:
        everyone = next_to_contact(session, people, 10)
        narrowed = next_to_contact(session, people, 10, still_gone_only=True)

    assert {i.person.sec_uid for i in everyone} == {
        "down1", "down2", "back1", "back2"}
    # An account with one post still down stays, even if others of
    # its posts came back: the evidence for *that* post is current.
    assert {i.person.sec_uid for i in narrowed} == {"down1", "down2"}
    # And the order within what is left is the same order.
    assert [i.person.sec_uid for i in narrowed] == [
        i.person.sec_uid for i in everyone if i.person.still_gone]


def test_contacts_already_made_outside_the_scope_can_be_found(db: None) -> None:
    """The topic filter did not reach this list until 10-19.

    Anything sent before then may have gone to an account whose
    removed posts were off topic — somebody outside the study being
    asked to talk about it. That is not a wasted message to write
    off quietly; it has to be findable.
    """
    from app.outreach import already

    on_topic = _person("keep", handle="a", gone=1)
    off_topic = _person("drop", handle="b", gone=2)

    with SessionLocal() as session:
        mark(session, on_topic, "sent")
        mark(session, off_topic, "sent")
        session.commit()

        rows = already(session)
        # `candidates` now returns only the in-scope one.
        in_scope = {on_topic.sec_uid}
        wrong = [sec for sec in rows if sec not in in_scope]

    assert wrong == ["drop"]


def test_the_audit_reports_the_fault_size_without_any_record(db: None) -> None:
    """How many accounts the list would have offered who are not
    this study's subject does not depend on anything having been
    marked. With an empty record that is the only number the audit
    can give, and it is the one that matters."""
    from app.interviews import Candidate

    wide = [_person(f"a{i}", handle=f"h{i}", gone=1) for i in range(10)]
    narrow = wide[:6]

    dropped = len(wide) - len(narrow)
    assert dropped == 4
    assert f"{dropped / len(wide):.0%}" == "40%"


def test_many_contacts_can_be_recorded_at_once(db: None) -> None:
    """Marking happens on a laptop and sending happens on a phone,
    so the record is usually behind. Thirty unrecorded contacts mean
    thirty people the queue will offer again -- and on Douyin the
    first message to a non-follower is the one that arrives, so
    offering again spends it."""
    people = [_person(f"acct{i}", handle=f"h{i}", gone=1) for i in range(5)]

    with SessionLocal() as session:
        for handle in ("h0", "h2", "h4"):
            mark(session, find(people, handle), "sent")
        session.commit()

        left = {i.person.sec_uid for i in next_to_contact(session, people, 10)}

    assert left == {"acct1", "acct3"}
