"""Scanning, hashing and incremental behaviour."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from filekeep.db import Database
from filekeep.index import hash_file, scan, walk

from .conftest import symlink_or_skip


def test_walk_finds_files_and_skips_hidden(tree: Path) -> None:
    (tree / ".hidden").write_text("x", encoding="utf-8")
    (tree / ".hiddendir").mkdir()
    (tree / ".hiddendir" / "inner.txt").write_text("x", encoding="utf-8")
    names = {entry.name for entry in walk(tree)}
    assert "one.jpg" in names
    assert "hidden" not in names
    assert "inner.txt" not in names


def test_walk_can_include_hidden(tree: Path) -> None:
    (tree / ".hidden").write_text("x", encoding="utf-8")
    names = {entry.name for entry in walk(tree, include_hidden=True)}
    assert ".hidden" in names


def test_walk_excludes_directories(tree: Path) -> None:
    names = {entry.name for entry in walk(tree, exclude=["code"])}
    assert "app.py" not in names
    assert "one.jpg" in names


def test_walk_sets_kind_and_ext(tree: Path) -> None:
    entry = next(item for item in walk(tree) if item.name == "one.jpg")
    assert entry.ext == "jpg"
    assert entry.kind == "image"
    assert entry.size == len(b"jpeg-payload")
    assert entry.root == str(tree.resolve())


def test_walk_skip_paths(tree: Path) -> None:
    skip = str(tree / "code")
    names = {entry.name for entry in walk(tree, skip_paths=[skip])}
    assert "app.py" not in names


def test_hash_file(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello")
    assert hash_file(path) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_hash_file_missing(tmp_path: Path) -> None:
    assert hash_file(tmp_path / "nope") is None


def test_hash_file_respects_limit(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 4096)
    assert hash_file(path, limit=1024) is None


def test_scan_counts(tree: Path, db: Database) -> None:
    result = scan(db, [tree], hash_policy="always")
    assert result.files == 8
    assert result.hashed == 8
    assert result.dirs == 4
    assert result.bytes > 0
    assert result.elapsed >= 0
    assert db.count() == 8


def test_scan_is_incremental(tree: Path, db: Database) -> None:
    first = scan(db, [tree], hash_policy="always")
    second = scan(db, [tree], hash_policy="always")
    assert first.hashed == 8
    assert second.hashed == 0
    assert second.files == 8


def test_scan_rehashes_changed_file(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="always")
    target = tree / "notes.txt"
    target.write_text("changed content", encoding="utf-8")
    os.utime(target, (0, 0))
    result = scan(db, [tree], hash_policy="always")
    assert result.hashed >= 1
    row = db.by_path(str(target))
    assert row is not None
    assert row.size == len("changed content")


def test_scan_never_policy_leaves_hashes_empty(tree: Path, db: Database) -> None:
    result = scan(db, [tree], hash_policy="never")
    assert result.hashed == 0
    assert all(row["hash"] is None for row in db.conn.execute("SELECT hash FROM files"))


def test_scan_auto_policy_skips_large_files(tree: Path, db: Database) -> None:
    big = tree / "big.bin"
    big.write_bytes(b"x" * 2048)
    scan(db, [tree], hash_policy="auto", max_hash_size=1024)
    row = db.by_path(str(big))
    assert row is not None and row.hash is None


def test_scan_prunes_deleted_files(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="always")
    (tree / "notes.txt").unlink()
    result = scan(db, [tree], hash_policy="always")
    assert result.pruned == 1
    assert db.by_path(str(tree / "notes.txt")) is None


def test_scan_no_prune_keeps_rows(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="always")
    (tree / "notes.txt").unlink()
    scan(db, [tree], hash_policy="always", prune=False)
    assert db.by_path(str(tree / "notes.txt")) is not None


def test_scan_records_roots_in_meta(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="always")
    assert db.meta_get("last_scan") is not None
    assert db.meta_get("last_scan_roots") == str(tree.resolve())


def test_scan_rejects_unknown_policy(tree: Path, db: Database) -> None:
    with pytest.raises(ValueError):
        scan(db, [tree], hash_policy="sometimes")


def test_scan_does_not_index_its_own_database(tree: Path, db: Database) -> None:
    scan(db, [tree], hash_policy="always")
    scan(db, [tree], hash_policy="always")
    assert db.by_path(str(db.path)) is None


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permissions are what makes a directory unreadable"
)
def test_scan_skips_unreadable_directories(tree: Path, db: Database) -> None:
    locked = tree / "locked"
    locked.mkdir()
    (locked / "inside.txt").write_text("x", encoding="utf-8")
    locked.chmod(0o000)
    try:
        result = scan(db, [tree], hash_policy="never")
    finally:
        locked.chmod(0o755)
    assert result.files >= 1
    assert db.by_path(str(locked / "inside.txt")) is None


def test_scan_handles_missing_root(db: Database, tmp_path: Path) -> None:
    result = scan(db, [tmp_path / "does-not-exist"], hash_policy="never")
    assert result.files == 0
    assert db.count() == 0


def test_broken_symlink_keeps_its_own_timestamp(tree: Path, db: Database) -> None:
    broken = tree / "broken-link"
    symlink_or_skip(broken, tree / "does-not-exist")
    scan(db, [tree], hash_policy="never")
    row = db.by_path(str(broken))
    assert row is not None
    assert row.size == 0
    assert row.mtime > 1_000_000  # not the 1970 epoch fallback
    assert row.is_link is True


def test_scan_follows_symlinks_when_asked(tree: Path, tmp_path: Path, db: Database) -> None:
    link = tree / "link.txt"
    symlink_or_skip(link, tree / "notes.txt")
    scan(db, [tree], hash_policy="never")
    row = db.by_path(str(link))
    assert row is not None and row.is_link is True
