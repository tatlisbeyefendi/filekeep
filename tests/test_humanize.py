"""Tests for the formatting and parsing helpers."""

from __future__ import annotations

import pytest

from filekeep.humanize import (
    ago,
    human_age,
    human_size,
    parse_duration,
    parse_size,
    percent,
    plural,
)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (12 * 1024, "12.0 KB"),
        (150 * 1024, "150 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (1024**4 * 3, "3.0 TB"),
    ],
)
def test_human_size(size: int, expected: str) -> None:
    assert human_size(size) == expected


def test_human_size_rejects_negative() -> None:
    with pytest.raises(ValueError):
        human_size(-1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("512", 512),
        ("1KB", 1024),
        ("1k", 1024),
        ("1.5 MB", 1572864),
        ("2GiB", 2 * 1024**3),
        ("10b", 10),
    ],
)
def test_parse_size(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "10 furlongs", "mb"])
def test_parse_size_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_size(text)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "just now"),
        (5, "just now"),
        (30, "30s"),
        (90, "1m"),
        (3600, "1h"),
        (86400, "1d"),
        (86400 * 20, "20d"),
        (86400 * 90, "3mo"),
        (86400 * 800, "2y"),
    ],
)
def test_human_age(seconds: float, expected: str) -> None:
    assert human_age(seconds) == expected


def test_human_age_clamps_negative() -> None:
    assert human_age(-100) == "just now"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", 30.0),
        ("15m", 900.0),
        ("12h", 43200.0),
        ("2d", 172800.0),
        ("2w", 1209600.0),
        ("6mo", 15552000.0),
        ("1y", 31536000.0),
        ("45", 45.0),
    ],
)
def test_parse_duration(text: str, expected: float) -> None:
    assert parse_duration(text) == expected


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_duration("soon")


def test_plural() -> None:
    assert plural(1, "file") == "1 file"
    assert plural(2, "file") == "2 files"
    assert plural(0, "copy", "copies") == "0 copies"
    assert plural(3, "directory", "directories") == "3 directories"


def test_ago() -> None:
    assert ago(1) == "just now"
    assert ago(86400 * 3) == "3d ago"


def test_percent() -> None:
    assert percent(1, 4) == 25.0
    assert percent(0, 0) == 0.0
    assert percent(5, 4) == 100.0
