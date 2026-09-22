"""One address is followed once, however many times it was copied."""

import pytest

from app.models import SharedLink
from app.resolve import resolve_pending

SHORT = "https://v.douyin.com/iRkQwBt/"
LANDED = "https://www.douyin.com/video/7686773732988082810"


def _link(session, when: str) -> SharedLink:
    link = SharedLink(
        participant_id="p1",
        platform="douyin",
        raw_text=f"5.61 复制打开抖音，看看【某人的作品】#lwl {SHORT} :8p",
        shared_at=when,
    )
    session.add(link)
    session.commit()
    return link


def test_the_same_address_copied_many_times_is_followed_once(session):
    """Douyin cannot be told to skip videos already seen.

    So a run re-copies them, and when the day's results run out the
    loop keeps copying whatever is still on screen -- one video
    produced 130 links in a single run. Following that address 130
    times is four minutes spent asking the same question, and the
    kind of thing that gets a study rate-limited out of data it
    cannot go back for.
    """
    from datetime import datetime

    for hour in range(4):
        _link(session, datetime(2026, 9, 22, 10 + hour))

    followed = []

    def follower(url: str) -> str:
        followed.append(url)
        return LANDED

    report = resolve_pending(session, follower=follower, pause_seconds=0)

    assert followed == [SHORT]
    assert (report.resolved, report.repeated) == (4, 3)
    ids = {link.video_id for link in session.query(SharedLink)}
    assert ids == {"7686773732988082810"}


def test_a_repeat_is_recorded_not_left_pending(session):
    """Skipping the request must not skip the row.

    A link left pending would come back on every later run, and would
    show on the dashboard as work waiting to be done for ever.
    """
    from datetime import datetime

    for hour in range(3):
        _link(session, datetime(2026, 9, 22, 10 + hour))
    resolve_pending(session, follower=lambda url: LANDED, pause_seconds=0)

    pending = session.query(SharedLink).filter(SharedLink.video_id.is_(None)).count()
    assert pending == 0


def test_a_different_address_is_still_followed(session):
    """The match is the address itself, not a guess about sameness."""
    from datetime import datetime

    _link(session, datetime(2026, 9, 22, 10))
    other = SharedLink(
        participant_id="p1",
        platform="douyin",
        raw_text="复制打开抖音 https://v.douyin.com/zzzOTHER/ 复制",
        shared_at=datetime(2026, 9, 22, 11),
    )
    session.add(other)
    session.commit()

    followed = []

    def follower(url: str) -> str:
        followed.append(url)
        return LANDED if "iRkQwBt" in url else LANDED.replace("810", "811")

    resolve_pending(session, follower=follower, pause_seconds=0)
    assert len(followed) == 2


@pytest.fixture()
def session(db):
    from app.db import SessionLocal

    with SessionLocal() as open_session:
        yield open_session
