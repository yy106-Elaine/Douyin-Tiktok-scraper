

def test_the_day_chart_ends_at_the_last_collection(db: None) -> None:
    """Not at today.

    Collection ended 2026-10-20 and the chart kept running to the
    current date, so by November a third of it was empty bars
    reporting that nothing was collected on days when nothing was
    being collected at all.
    """
    from datetime import date, datetime

    from app.db import SessionLocal
    from app.models import CaptureEvent, DouyinPost
    from app.views import daily_counts

    with SessionLocal() as session:
        event = CaptureEvent(
            participant_id="P001", device_id="d", platform="douyin",
            fingerprint="f", capture_date="2026-10-18",
            captured_at=datetime(2026, 10, 18, 12), payload="{}",
        )
        session.add(event)
        session.flush()
        session.add_all([
            DouyinPost(capture_event_id=event.id, participant_id="P001",
                       captured_at=datetime(2026, 10, 18, 12),
                       video_id="a", caption="#wlw"),
            DouyinPost(capture_event_id=event.id, participant_id="P001",
                       captured_at=datetime(2026, 10, 20, 12),
                       video_id="b", caption="#wlw"),
        ])
        session.commit()

        days = daily_counts(session, "douyin", days=3,
                            now=datetime(2026, 11, 4),
                            until=date(2026, 10, 20))

    assert [d for d, _ in days] == ["2026-10-18", "2026-10-19", "2026-10-20"]
    # The empty day inside the range stays: a collection day that
    # collected nothing is a fact about that day.
    assert dict(days)["2026-10-19"] == 0
