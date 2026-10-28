"""Extension to kind mapping."""

from __future__ import annotations

import pytest

from filekeep.kinds import (
    EXT_KINDS,
    ext_of,
    folder_for_kind,
    kind_for,
    known_kinds,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("photo.JPG", "image"),
        ("clip.mkv", "video"),
        ("song.flac", "audio"),
        ("report.pdf", "document"),
        ("book.xlsx", "sheet"),
        ("deck.pptx", "slides"),
        ("backup.tar.gz", "archive"),
        ("main.rs", "code"),
        ("data.parquet", "data"),
        ("font.woff2", "font"),
        ("setup.exe", "app"),
        ("weird.xyz", "other"),
        ("README", "other"),
    ],
)
def test_kind_for_name(name: str, expected: str) -> None:
    assert kind_for(ext_of(name)) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.txt", "txt"),
        ("a.TXT", "txt"),
        ("a.tar.gz", "gz"),
        ("archive", ""),
        (".bashrc", ""),
        ("trailing.", ""),
    ],
)
def test_ext_of(name: str, expected: str) -> None:
    assert ext_of(name) == expected


def test_kind_for_empty_ext() -> None:
    assert kind_for("") == "other"


def test_folder_for_kind() -> None:
    assert folder_for_kind("image") == "Photos"
    assert folder_for_kind("sheet") == "Spreadsheets"
    assert folder_for_kind("nonexistent") == "Other"


def test_known_kinds_is_stable() -> None:
    kinds = known_kinds()
    assert kinds[0] == "image"
    assert "other" in kinds
    assert len(kinds) == len(set(kinds))


def test_every_extension_maps_to_a_known_kind() -> None:
    assert set(EXT_KINDS.values()) <= set(known_kinds())
