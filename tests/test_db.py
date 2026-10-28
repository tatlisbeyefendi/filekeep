"""Storage layer: schema, upserts, tags, trash and meta."""

from __future__ import annotations

from pathlib import Path

import pytest

from filekeep.db import Database, default_data_dir, default_db_path


def test_schema_is_created(db: Database) -> None:
    tables = {
        row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"files", "tags", "trash", "meta"} <= tables
    assert db.meta_get("schema_version") == "1"


def test_default_paths_follow_filekeep_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FILEKEEP_HOME", str(tmp_path / "custom"))
    assert default_data_dir() == tmp_path / "custom"
    assert default_db_path() == tmp_path / "custom" / "index.db"


def test_default_paths_use_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FILEKEEP_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_db_path() == tmp_path / "xdg" / "filekeep" / "index.db"


def test_upsert_and_lookup(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 5, 1000.0, False, "h1")])
    row = db.by_path("/root/a.txt")
    assert row is not None
    assert row.size == 5
    assert row.hash == "h1"
    assert row.missing is False
    assert db.count() == 1


def test_upsert_is_idempotent_and_updates(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 5, 1000.0, False, "h1")])
    first = db.by_path("/root/a.txt")
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 9, 2000.0, False, "h2")])
    second = db.by_path("/root/a.txt")
    assert db.count() == 1
    assert first is not None and second is not None
    assert second.size == 9
    assert second.hash == "h2"


def test_upsert_keeps_old_hash_when_new_is_none(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 5, 1.0, False, "h1")])
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 5, 1.0, False)])
    row = db.by_path("/root/a.txt")
    assert row is not None and row.hash == "h1"


def test_update_hash(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 5, 1.0, False)])
    db.update_hash("/root/a.txt", "digest")
    row = db.by_path("/root/a.txt")
    assert row is not None and row.hash == "digest"


def test_prune_root_removes_only_unknown_paths(db: Database) -> None:
    rows = [
        ("/root", f"/root/{name}.txt", f"{name}.txt", "txt", "document", 1, 1.0, False, "h")
        for name in ("a", "b", "c")
    ]
    db.upsert_files(rows)
    removed = db.prune_root("/root", ["/root/a.txt", "/root/b.txt"])
    assert removed == 1
    assert db.by_path("/root/c.txt") is None
    assert db.count() == 2


def test_delete_and_move_path(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 1, 1.0, False, "h")])
    db.move_path("/root/a.txt", "/root/sub/b.txt")
    assert db.by_path("/root/a.txt") is None
    moved = db.by_path("/root/sub/b.txt")
    assert moved is not None and moved.name == "b.txt"
    db.delete_file("/root/sub/b.txt")
    assert db.count() == 0


def test_missing_rows_are_hidden_from_count(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 1, 1.0, False, "h")])
    db.set_missing(["/root/a.txt"])
    assert db.count() == 0
    assert db.count(include_missing=True) == 1


def test_tags(db: Database) -> None:
    db.upsert_files([("/root", "/root/a.txt", "a.txt", "txt", "document", 1, 1.0, False, "h")])
    assert db.add_tag("/root/a.txt", "keep") is True
    assert db.add_tag("/root/a.txt", "keep") is False
    row = db.by_path("/root/a.txt")
    assert row is not None
    assert db.tags_for(row.id) == ["keep"]
    assert db.all_tags() == [("keep", 1)]
    assert db.remove_tag("/root/a.txt", "keep") is True
    assert db.remove_tag("/root/a.txt", "keep") is False
    assert db.tags_for(row.id) == []


def test_tag_unknown_path_raises(db: Database) -> None:
    with pytest.raises(KeyError):
        db.add_tag("/nope", "x")


def test_trash_roundtrip(db: Database) -> None:
    entry_id = db.trash_add("/root/a.txt", "/data/trash/1/a.txt", 42)
    assert entry_id > 0
    entries = db.trash_entries()
    assert len(entries) == 1
    assert db.trash_get(entry_id)["size"] == 42
    db.trash_mark_restored(entry_id)
    assert db.trash_entries() == []
    assert len(db.trash_entries(include_restored=True)) == 1


def test_meta_roundtrip(db: Database) -> None:
    assert db.meta_get("missing") is None
    assert db.meta_get("missing", "fallback") == "fallback"
    db.meta_set("key", "value")
    assert db.meta_get("key") == "value"
    db.meta_set("key", "other")
    assert db.meta_get("key") == "other"


def test_open_missing_index_without_create(tmp_path: Path) -> None:
    database = Database(tmp_path / "nope" / "index.db", create=False)
    with pytest.raises(FileNotFoundError):
        _ = database.conn


def test_context_manager_closes_and_reopens(isolated_home) -> None:
    with Database(isolated_home / "index.db") as database:
        database.upsert_files([("/r", "/r/a", "a", "", "other", 1, 1.0, False, "h")])
    assert database._conn is None
    assert database.count() == 1  # a closed database reconnects on demand
    database.close()


def test_roots_reports_scan_roots(db: Database) -> None:
    db.upsert_files(
        [
            ("/one", "/one/a.txt", "a.txt", "txt", "document", 1, 1.0, False, "h"),
            ("/two", "/two/b.txt", "b.txt", "txt", "document", 1, 1.0, False, "h2"),
        ]
    )
    assert db.roots() == ["/one", "/two"]
