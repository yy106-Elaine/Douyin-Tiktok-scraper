"""Recovering publication time from a video id.

A takedown study measures from publication, so where this number comes
from is a methodological question, not a display detail. These tests
pin both the arithmetic and the refusals.
"""
from datetime import datetime

import pytest

from app.snowflake import derivation_is_verified, posted_at_from_video_id
from app.views import publication


def test_the_high_bits_decode_to_the_creation_second():
    # 7301234567890123456 >> 32 == 1699951143
    assert posted_at_from_video_id("7301234567890123456") == datetime(
        2023, 11, 14, 8, 39, 3
    )


def test_larger_ids_decode_to_later_times():
    """Sanity check on the layout: ids are minted in time order."""
    early = posted_at_from_video_id("6800000000000000000")
    late = posted_at_from_video_id("7539000000000000000")
    assert early is not None and late is not None
    assert early < late
    assert early.year == 2020
    assert late.year == 2025


def test_an_integer_id_is_accepted():
    assert posted_at_from_video_id(7301234567890123456) == datetime(
        2023, 11, 14, 8, 39, 3
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "not-an-id",
        "tiktok://post/abcdef",   # the synthetic form the reference app stored
        "123",                    # too short to be a snowflake
        "12345678901234567890",   # too long
        "1000000000000000000",    # decodes to 1977, before either platform
    ],
)
def test_undecodable_values_return_nothing_rather_than_a_date(value):
    """A wrong date silently becomes a data point; None does not."""
    assert posted_at_from_video_id(value) is None


def test_a_future_publication_time_is_refused():
    real = "7301234567890123456"
    assert posted_at_from_video_id(real, now=datetime(2023, 11, 14, 9, 0)) is not None
    assert posted_at_from_video_id(real, now=datetime(2020, 1, 1)) is None


def test_douyin_is_not_claimed_as_verified():
    """The arithmetic is applied to both; only one has been checked."""
    assert derivation_is_verified("tiktok") is True
    assert derivation_is_verified("douyin") is False


class TestPrecedence:
    """Which source of publication time wins, and what it is labelled."""

    def test_the_id_beats_what_the_screen_showed(self):
        posted_at, display, source = publication(
            "7301234567890123456", datetime(2026, 1, 1), "11h ago"
        )
        assert posted_at == datetime(2023, 11, 14, 8, 39, 3)
        assert display == "2023-11-14 08:39"
        assert source == "video id"

    def test_the_parsed_screen_value_is_the_fallback(self):
        posted_at, display, source = publication(None, datetime(2026, 5, 4, 7, 6), "5-4")
        assert posted_at == datetime(2026, 5, 4, 7, 6)
        assert display == "2026-05-04 07:06"
        assert source == "screen"

    def test_an_unparsed_string_still_beats_an_empty_column(self):
        posted_at, display, source = publication(None, None, "5-31")
        assert posted_at is None
        assert display == "5-31"
        assert source == "as shown"

    def test_nothing_known_is_reported_as_nothing(self):
        assert publication(None, None, None) == (None, None, "")
