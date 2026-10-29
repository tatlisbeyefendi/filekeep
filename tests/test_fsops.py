"""Collision handling, moving, trashing, restoring and undo."""

from __future__ import annotations

from pathlib import Path

import pytest

from filekeep.db import Database
from filekeep.fsops import (
    Plan,
    apply_moves,
    copy_file,
    move_file,
    restore_paths,
    trash_paths,
    undo,
    unique_path,
)
from filekeep.journal import Journal

from .conftest import write


def test_unique_path_returns_same_when_free(tmp_path: Path) -> None:
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a.txt"


def test_unique_path_numbers_collisions(tmp_path: Path) -> None:
    write(tmp_path / "a.txt")
    write(tmp_path / "a (2).txt")
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a (3).txt"


def test_move_file_creates_parents(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt", "hello")
    target = move_file(source, tmp_path / "deep" / "nested" / "b.txt")
    assert target.exists()
    assert not source.exists()
    assert target.read_text() == "hello"


def test_move_file_avoids_collision(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt", "new")
    existing = write(tmp_path / "b.txt", "old")
    moved = move_file(source, existing)
    assert moved.name == "b (2).txt"
    assert existing.read_text() == "old"
    assert moved.read_text() == "new"


def test_move_file_overwrite(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt", "new")
    target = write(tmp_path / "b.txt", "old")
    move_file(source, target, overwrite=True)
    assert target.read_text() == "new"


def test_copy_file(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt", "hello")
    copied = copy_file(source, tmp_path / "b.txt")
    assert source.exists() and copied.exists()
    assert copied.read_text() == "hello"


def test_apply_moves_dry_run(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt")
    plans = [Plan(source=str(source), target=str(tmp_path / "dest" / "a.txt"))]
    done = apply_moves(plans, dry_run=True)
    assert len(done) == 1
    assert source.exists()


def test_apply_moves_real(tmp_path: Path, db: Database, journal: Journal) -> None:
    source = write(tmp_path / "a.txt", "x")
    db.upsert_files([(str(tmp_path), str(source), "a.txt", "txt", "document", 1, 1.0, False, "h")])
    plans = [Plan(source=str(source), target=str(tmp_path / "dest" / "a.txt"))]
    done = apply_moves(plans, db=db, journal=journal, dry_run=False)
    assert len(done) == 1
    assert Path(done[0].target).exists()
    assert db.by_path(str(source)) is None
    assert db.by_path(done[0].target) is not None
    assert journal.count() == 1


def test_apply_moves_skips_missing_source(tmp_path: Path) -> None:
    plans = [Plan(source=str(tmp_path / "nope.txt"), target=str(tmp_path / "x.txt"))]
    assert apply_moves(plans, dry_run=False) == []


def test_apply_moves_skips_unchanged(tmp_path: Path) -> None:
    source = write(tmp_path / "a.txt")
    plans = [Plan(source=str(source), target=str(source))]
    assert apply_moves(plans, dry_run=False) == []


def test_apply_moves_copy(tmp_path: Path, journal: Journal) -> None:
    source = write(tmp_path / "a.txt")
    plans = [Plan(source=str(source), target=str(tmp_path / "b.txt"))]
    done = apply_moves(plans, journal=journal, copy=True, dry_run=False)
    assert source.exists() and Path(done[0].target).exists()


def test_trash_and_restore_roundtrip(tmp_path: Path, db: Database, journal: Journal) -> None:
    source = write(tmp_path / "a.txt", "hello")
    db.upsert_files([(str(tmp_path), str(source), "a.txt", "txt", "document", 5, 1.0, False, "h")])
    trashed = trash_paths(
        [source], data_dir=tmp_path / "data", db=db, journal=journal, dry_run=False
    )
    assert len(trashed) == 1
    source_path, trashed_path = trashed[0]
    assert not Path(source_path).exists()
    assert Path(trashed_path).exists()
    assert db.by_path(source_path) is None
    entries = db.trash_entries()
    assert len(entries) == 1

    restored = restore_paths(entries, db=db, journal=journal, dry_run=False)
    assert restored[0][1] == source_path
    assert Path(source_path).read_text() == "hello"
    assert db.trash_entries() == []


def test_trash_dry_run(tmp_path: Path, db: Database) -> None:
    source = write(tmp_path / "a.txt")
    done = trash_paths([source], data_dir=tmp_path / "data", db=db, dry_run=True)
    assert len(done) == 1
    assert source.exists()
    assert db.trash_entries() == []


def test_restore_avoids_overwriting_the_original(tmp_path: Path, db: Database) -> None:
    source = write(tmp_path / "a.txt", "original")
    trash_paths([source], data_dir=tmp_path / "data", db=db, dry_run=False)
    write(source, "replacement")
    restored = restore_paths(db.trash_entries(), db=db, dry_run=False)
    assert restored[0][1].endswith("a (2).txt")
    assert Path(restored[0][1]).read_text() == "original"
    assert source.read_text() == "replacement"


def test_undo_move(tmp_path: Path, db: Database, journal: Journal) -> None:
    source = write(tmp_path / "a.txt")
    db.upsert_files([(str(tmp_path), str(source), "a.txt", "txt", "document", 1, 1.0, False, "h")])
    plans = [Plan(source=str(source), target=str(tmp_path / "dest" / "a.txt"))]
    apply_moves(plans, db=db, journal=journal, dry_run=False)
    undone = undo(journal=journal, db=db, steps=1)
    assert undone[0][0] == "move"
    assert source.exists()
    assert journal.is_empty()


def test_undo_copy_deletes_the_copy(tmp_path: Path, journal: Journal) -> None:
    source = write(tmp_path / "a.txt")
    plans = [Plan(source=str(source), target=str(tmp_path / "b.txt"))]
    apply_moves(plans, journal=journal, copy=True, dry_run=False)
    undo(journal=journal, steps=1)
    assert source.exists()
    assert not (tmp_path / "b.txt").exists()


def test_undo_trash_restores(tmp_path: Path, db: Database, journal: Journal) -> None:
    source = write(tmp_path / "a.txt", "hello")
    trash_paths([source], data_dir=tmp_path / "data", db=db, journal=journal, dry_run=False)
    undone = undo(journal=journal, db=db, steps=1)
    assert undone[0][0] == "trash"
    assert source.read_text() == "hello"


def test_undo_multiple_steps(tmp_path: Path, journal: Journal) -> None:
    for number in range(3):
        source = write(tmp_path / f"f{number}.txt")
        apply_moves(
            [Plan(source=str(source), target=str(tmp_path / "dest" / source.name))],
            journal=journal,
            dry_run=False,
        )
    undone = undo(journal=journal, steps=3)
    assert len(undone) == 3
    assert all(Path(item[2]).exists() for item in undone)
    assert journal.is_empty()


def test_undo_dry_run_keeps_the_journal(tmp_path: Path, journal: Journal) -> None:
    source = write(tmp_path / "a.txt")
    apply_moves(
        [Plan(source=str(source), target=str(tmp_path / "dest" / "a.txt"))],
        journal=journal,
        dry_run=False,
    )
    undone = undo(journal=journal, steps=1, dry_run=True)
    assert len(undone) == 1
    assert journal.count() == 1
    assert not source.exists()


def test_undo_on_empty_journal(journal: Journal) -> None:
    assert undo(journal=journal, steps=5) == []


def test_undo_when_the_target_vanished(tmp_path: Path, journal: Journal) -> None:
    source = write(tmp_path / "a.txt")
    plans = [Plan(source=str(source), target=str(tmp_path / "dest" / "a.txt"))]
    apply_moves(plans, journal=journal, dry_run=False)
    (tmp_path / "dest" / "a.txt").unlink()
    undone = undo(journal=journal, steps=1)
    assert undone[0][1].endswith("a.txt")


def test_undo_restores_a_broken_symlink(tmp_path: Path, journal: Journal) -> None:
    link = tmp_path / "broken-link"
    link.symlink_to(tmp_path / "nowhere")
    plans = [Plan(source=str(link), target=str(tmp_path / "dest" / "broken-link"))]
    apply_moves(plans, journal=journal, dry_run=False)
    assert (tmp_path / "dest" / "broken-link").is_symlink()
    undone = undo(journal=journal, steps=1)
    assert undone[0][0] == "move"
    assert link.is_symlink()
    assert not (tmp_path / "dest" / "broken-link").exists()


def test_undo_handles_a_symlink_whose_target_moved(tmp_path: Path, journal: Journal) -> None:
    target = write(tmp_path / "a" / "f.txt", "hello")
    link = tmp_path / "b" / "f-link.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    plans = [
        Plan(source=str(target), target=str(tmp_path / "dest" / "f.txt")),
        Plan(source=str(link), target=str(tmp_path / "dest" / "f-link.txt")),
    ]
    apply_moves(plans, journal=journal, dry_run=False)
    undo(journal=journal, steps=2)
    assert target.read_text() == "hello"
    assert link.is_symlink()
    assert not (tmp_path / "dest" / "f.txt").exists()


def test_trash_keeps_a_broken_symlink(tmp_path: Path, db: Database) -> None:
    link = tmp_path / "broken"
    link.symlink_to(tmp_path / "nowhere")
    done = trash_paths([link], data_dir=tmp_path / "data", db=db, dry_run=False)
    assert len(done) == 1
    assert not link.is_symlink()


@pytest.mark.parametrize("count", [1, 2, 5])
def test_journal_pop_more_than_available(tmp_path: Path, count: int) -> None:
    journal = Journal(tmp_path / "journal.jsonl")
    journal.record("move", src="/a", dst="/b")
    assert len(journal.pop(count)) == 1
    assert journal.is_empty()
