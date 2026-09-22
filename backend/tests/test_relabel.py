"""Re-labelling the TikTok rows that stored a suggestion as a query."""
from __future__ import annotations

from app import relabel
from app.db import SessionLocal
from app.models import TikTokPost


def _post(marker: str, feed: str | None) -> TikTokPost:
    from datetime import datetime

    return TikTokPost(
        capture_event_id=1,
        participant_id="P001",
        caption=marker,
        captured_at=datetime(2026, 9, 21, 20, 18),
        feed=feed,
    )


def test_a_player_suggestion_is_re_labelled(db):
    with SessionLocal() as session:
        session.add(_post("a", "search:brys lovely beloved wife social media"))
        session.commit()

        assert relabel.relabel(session, relabel.mislabelled(session)) == 1
        assert (
            session.query(TikTokPost).one().feed
            == "anchor:brys lovely beloved wife social media"
        )


def test_the_grid_rows_are_left_alone(db):
    """The results grid does show the query someone typed.

    `search:<query>:<sort>` is its shape, and those rows are the real
    sampling frame -- the whole point of separating the two.
    """
    with SessionLocal() as session:
        session.add(_post("a", "search:chinese lesbian:Latest"))
        session.add(_post("b", "recommend"))
        session.add(_post("c", None))
        session.commit()

        assert relabel.mislabelled(session) == []


def test_running_it_twice_changes_nothing_more(db):
    with SessionLocal() as session:
        session.add(_post("a", "search:gf car trend"))
        session.commit()
        relabel.relabel(session, relabel.mislabelled(session))
        assert relabel.mislabelled(session) == []
