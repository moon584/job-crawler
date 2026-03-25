from datetime import datetime

from crawler.utils import normalize_category_id, parse_publish_time


def test_parse_full_datetime() -> None:
    result = parse_publish_time("2026-03-23 12:34:56")
    assert result is not None
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 23
    assert result.hour == 12
    assert result.minute == 34
    assert result.second == 56


def test_parse_date_only_sets_midnight() -> None:
    result = parse_publish_time("2026-03-23")
    assert result is not None
    assert result.hour == 0 and result.minute == 0 and result.second == 0


def test_parse_chinese_format() -> None:
    result = parse_publish_time("2026年03月23日")
    assert result is not None
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 23


def test_parse_invalid_returns_none() -> None:
    assert parse_publish_time("invalid-date") is None


def test_normalize_category_id_inserts_missing_zero() -> None:
    assert normalize_category_id("4001001") == "40001001"


def test_normalize_category_id_keeps_valid_value() -> None:
    assert normalize_category_id("40001001") == "40001001"


def test_normalize_category_id_accepts_short_numeric() -> None:
    assert normalize_category_id("123456") == "123456"


def test_normalize_category_id_uppercases_text() -> None:
    assert normalize_category_id("c001a01") == "C001A01"
