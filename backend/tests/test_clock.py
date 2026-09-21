"""Stored in UTC, read in the researcher's own day.

A run at 22:52 in Boston is 02:52 the next day in UTC. The per-day
chart put that evening's work under tomorrow and showed zero for the
day it happened on, which is the one question the chart is for.
"""
from __future__ import annotations

from datetime import date, datetime

from app.clock import local, local_date, start_of_local_day
from app.db import SessionLocal
from app.views import daily_counts


def test_an_evening_run_belongs_to_the_evening():
    stored = datetime(2026, 9, 21, 2, 52)  # UTC
    assert local(stored) == datetime(2026, 9, 20, 22, 52)
    assert local_date(stored) == date(2026, 9, 20)


def test_the_offset_follows_daylight_saving():
    # September is EDT (UTC-4); November is EST (UTC-5).
    assert local(datetime(2026, 9, 16, 8, 30)) == datetime(2026, 9, 16, 4, 30)
    assert local(datetime(2023, 11, 14, 8, 39)) == datetime(2023, 11, 14, 3, 39)


def test_a_local_day_starts_at_local_midnight():
    # Midnight on 20 September in Eastern time is 04:00 UTC.
    assert start_of_local_day(date(2026, 9, 20)) == datetime(2026, 9, 20, 4, 0)


def test_the_chart_counts_an_evening_run_on_that_evening(client, api_key):
    client.post(
        "/api/captures/batch",
        json={
            "device_id": "pixel-7a",
            "captures": [
                {
                    "platform_package": "com.ss.android.ugc.aweme",
                    "fingerprint": "douyin::a::b",
                    # 22:52 on the 20th, Eastern.
                    "captured_at": "2026-09-21T02:52:00Z",
                    "payload": {"author_name": "a", "caption": "#lwl"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
    )

    with SessionLocal() as session:
        counts = dict(
            daily_counts(session, "douyin", days=3, now=datetime(2026, 9, 21, 2, 55))
        )

    assert counts["2026-09-20"] == 1
    assert counts.get("2026-09-21", 0) == 0
