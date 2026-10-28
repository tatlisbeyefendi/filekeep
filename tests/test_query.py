"""Filtering, sorting, duplicate detection and statistics."""

from __future__ import annotations

import os
from pathlib import Path

from filekeep.db import Database
from filekeep.index import scan
from filekeep.query import (
    FileFilter,
    duplicate_groups,
    search,
    stats,
    unhashed,
)


def names(rows) -> list[str]:
    return [row.name for row in rows]


def test_search_all(indexed: Database) -> None:
    assert len(search(indexed)) == 8


def test_filter_by_kind(indexed: Database) -> None:
    rows = search(indexed, FileFilter(kinds=["image"]))
    assert sorted(names(rows)) == ["one-copy.jpg", "one.jpg", "two.png"]


def test_filter_by_ext(indexed: Database) -> None:
    assert names(search(indexed, FileFilter(exts=["py"]))) == ["app.py", "mod.py"]


def test_filter_by_name_substring(indexed: Database) -> None:
    assert sorted(names(search(indexed, FileFilter(name_like="copy")))) == [
        "notes-copy.txt",
        "one-copy.jpg",
    ]


def test_filter_by_glob(indexed: Database) -> None:
    assert names(search(indexed, FileFilter(name_glob="*.py"))) == ["app.py", "mod.py"]


def test_filter_by_regex(indexed: Database) -> None:
    assert sorted(names(search(indexed, FileFilter(name_regex=r"^notes")))) == [
        "notes-copy.txt",
        "notes.txt",
    ]


def test_filter_by_size(indexed: Database) -> None:
    rows = search(indexed, FileFilter(min_size=10))
    assert all(row.size >= 10 for row in rows)


def test_filter_by_path_prefix(indexed: Database, tree: Path) -> None:
    rows = search(indexed, FileFilter(roots=[str(tree / "photos")]))
    assert sorted(names(rows)) == ["one-copy.jpg", "one.jpg", "two.png"]


def test_filter_older_than(indexed: Database, tree: Path) -> None:
    old = tree / "notes.txt"
    os.utime(old, (0, 0))
    scan(indexed, [tree], hash_policy="never")
    rows = search(indexed, FileFilter(older_than=86400))
    assert names(rows) == ["notes.txt"]


def test_filter_newer_than(indexed: Database, tree: Path) -> None:
    old = tree / "notes.txt"
    os.utime(old, (0, 0))
    scan(indexed, [tree], hash_policy="never")
    rows = search(indexed, FileFilter(newer_than=3600))
    assert "notes.txt" not in names(rows)


def test_filter_excludes_links(indexed: Database, tree: Path) -> None:
    link = tree / "link.txt"
    link.symlink_to(tree / "notes.txt")
    scan(indexed, [tree], hash_policy="never")
    assert "link.txt" in names(search(indexed))
    assert "link.txt" not in names(search(indexed, FileFilter(include_links=False)))


def test_filter_by_tag(indexed: Database, tree: Path) -> None:
    indexed.add_tag(str(tree / "notes.txt"), "keep")
    assert names(search(indexed, FileFilter(tags=["keep"]))) == ["notes.txt"]


def test_multiple_tags_are_anded(indexed: Database, tree: Path) -> None:
    indexed.add_tag(str(tree / "notes.txt"), "keep")
    indexed.add_tag(str(tree / "notes.txt"), "work")
    indexed.add_tag(str(tree / "code" / "app.py"), "work")
    rows = search(indexed, FileFilter(tags=["keep", "work"]))
    assert names(rows) == ["notes.txt"]


def test_sorting(indexed: Database) -> None:
    by_size = search(indexed, sort="size")
    assert by_size[0].size >= by_size[-1].size
    by_name = search(indexed, sort="name")
    assert names(by_name) == sorted(names(by_name))
    reversed_rows = search(indexed, sort="name", reverse=True)
    assert names(reversed_rows) == list(reversed(names(by_name)))


def test_limit(indexed: Database) -> None:
    assert len(search(indexed, limit=3)) == 3


def test_duplicates(indexed: Database) -> None:
    groups = duplicate_groups(indexed)
    assert len(groups) == 2
    found = sorted(sorted(names(group)) for group in groups)
    assert found == [["notes-copy.txt", "notes.txt"], ["one-copy.jpg", "one.jpg"]]


def test_duplicates_min_size(indexed: Database) -> None:
    assert duplicate_groups(indexed, min_size=len(b"jpeg-payload")) == [
        group for group in duplicate_groups(indexed) if group[0].size >= len(b"jpeg-payload")
    ]


def test_duplicates_respect_filter(indexed: Database) -> None:
    groups = duplicate_groups(indexed, spec=FileFilter(kinds=["document"]))
    assert len(groups) == 1
    assert sorted(names(groups[0])) == ["notes-copy.txt", "notes.txt"]


def test_duplicates_ignore_unhashed(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="never")
    assert duplicate_groups(db) == []


def test_unhashed_lists_candidates(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="never")
    assert len(unhashed(db)) == 8
    assert unhashed(db, min_size=10**9) == []


def test_stats(indexed: Database) -> None:
    result = stats(indexed)
    assert result.files == 8
    assert result.size > 0
    assert result.missing == 0
    assert sum(item.files for item in result.kinds) == 8
    assert result.oldest is not None and result.newest is not None
    assert result.oldest.mtime <= result.newest.mtime
    assert result.years


def test_stats_on_empty_index(db: Database) -> None:
    result = stats(db)
    assert result.files == 0
    assert result.kinds == []
    assert result.oldest is None


def test_build_returns_one_equals_one_when_empty() -> None:
    clause, params = FileFilter().build()
    assert clause == "missing = 0"
    assert params == []


def test_build_uses_parameters() -> None:
    clause, params = FileFilter(kinds=["image"], min_size=10).build(now=1000.0)
    assert "kind IN (?)" in clause
    assert "size >= ?" in clause
    assert params == ["image", 10]


def test_missing_rows_excluded_by_default(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="never")
    db.set_missing([str(tree / "notes.txt")])
    assert "notes.txt" not in names(search(db))
    assert "notes.txt" in names(search(db, FileFilter(include_missing=True)))
