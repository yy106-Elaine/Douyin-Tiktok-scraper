"""Whether the instrument is still collecting has to be visible."""

from datetime import datetime, timedelta

import pytest

from app.views import last_runs


@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session


def _post(session, when: datetime, n: int = 1) -> None:
    from app.models import CaptureEvent, YouTubePost

    for index in range(n):
        event = CaptureEvent(
            participant_id="p1",
            device_id="youtube-api",
            platform="youtube",
            fingerprint=f"{when.isoformat()}-{index}",
            capture_date=when.date().isoformat(),
            captured_at=when,
            payload="{}",
        )
        session.add(event)
        session.flush()
        session.add(YouTubePost(
            capture_event_id=event.id,
            participant_id="p1",
            captured_at=when,
            video_id=f"v{when.timestamp():.0f}{index}",
        ))
    session.commit()


def test_a_platform_that_never_collected_says_so(session):
    runs = {r.platform: r for r in last_runs(session)}
    assert runs["douyin"].last_collected is None
    assert runs["douyin"].hours_ago() is None


def test_the_last_batch_and_its_size_are_reported(session):
    now = datetime(2026, 9, 24, 19, 0)
    _post(session, now - timedelta(hours=6), 136)
    _post(session, now, 86)

    run = {r.platform: r for r in last_runs(session, now=now)}["youtube"]
    assert run.last_collected == now
    assert run.last_batch == 86
    assert round(run.hours_ago(now)) == 0


def test_two_batches_in_a_day_are_counted_as_two(session):
    """A scheduled job had been collecting for weeks unnoticed.

    One arrival time a day is one thing collecting. Two is two, and
    the page should say so rather than leave it to be worked out from
    a tally that looks larger than the last command reported.
    """
    now = datetime(2026, 9, 24, 19, 0)
    _post(session, now - timedelta(hours=6), 136)
    _post(session, now, 86)

    run = {r.platform: r for r in last_runs(session, now=now)}["youtube"]
    assert run.batches_today == 2


def test_silence_is_measured_in_days_once_it_is_long(session):
    now = datetime(2026, 9, 24, 19, 0)
    _post(session, now - timedelta(days=3))

    run = {r.platform: r for r in last_runs(session, now=now)}["youtube"]
    assert run.batches_today == 0
    assert round(run.hours_ago(now)) == 72
