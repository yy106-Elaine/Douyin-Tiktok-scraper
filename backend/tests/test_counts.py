from app.counts import is_approximate, parse_count


def test_plain_integers_round_trip():
    assert parse_count("1234") == 1234
    assert parse_count("1,234") == 1234
    assert parse_count(42) == 42


def test_english_abbreviations():
    assert parse_count("74.9K") == 74900
    assert parse_count("9M") == 9_000_000
    assert parse_count("1.2B") == 1_200_000_000


def test_chinese_abbreviations():
    assert parse_count("12.3万") == 123_000
    assert parse_count("1.2亿") == 120_000_000
    assert parse_count("5万") == 50_000


def test_missing_and_unparseable():
    assert parse_count(None) is None
    assert parse_count("") is None
    assert parse_count("暂无") is None


def test_approximation_flag():
    assert is_approximate("12.3万") is True
    assert is_approximate("74.9K") is True
    assert is_approximate("1234") is False
    assert is_approximate(None) is False
