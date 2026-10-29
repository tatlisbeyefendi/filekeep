"""Filesystem primitives: collision-safe moves, copies, trash and undo."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from filekeep.db import Database
from filekeep.journal import Journal


def lexists(path: str | os.PathLike[str]) -> bool:
    """``os.path.lexists``: true for broken symlinks too, where ``Path.exists`` lies."""
    return os.path.lexists(path)


@dataclass(frozen=True)
class Plan:
    """A single planned change on disk."""

    source: str
    target: str
    reason: str = ""

    @property
    def moved(self) -> bool:
        return self.source != self.target


def unique_path(target: str | os.PathLike[str]) -> Path:
    """Return ``target`` if it is free, otherwise ``name (2).ext``, ``name (3).ext`` …"""
    path = Path(target)
    if not path.exists() and not path.is_symlink():
        return path
    stem, suffix = path.stem, path.suffix
    for counter in range(2, 10_000):
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise OSError(f"cannot find a free name for {path}")  # pragma: no cover - pathological


def move_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> Path:
    """Move ``source`` to ``target``, creating parents and avoiding collisions by default."""
    source_path = Path(source)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and (target_path.exists() or target_path.is_symlink()):
        target_path = unique_path(target_path)
    shutil.move(str(source_path), str(target_path))
    return target_path


def copy_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> Path:
    """Copy ``source`` to ``target`` with the same collision policy as :func:`move_file`."""
    source_path = Path(source)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and (target_path.exists() or target_path.is_symlink()):
        target_path = unique_path(target_path)
    shutil.copy2(str(source_path), str(target_path))
    return target_path


def apply_moves(
    plans: list[Plan],
    *,
    db: Database | None = None,
    journal: Journal | None = None,
    copy: bool = False,
    dry_run: bool = True,
    op: str = "move",
) -> list[Plan]:
    """Execute (or pretend to execute) a list of plans, returning what happened."""
    done: list[Plan] = []
    for plan in plans:
        if not plan.moved:
            continue
        if dry_run:
            done.append(plan)
            continue
        source = Path(plan.source)
        if not lexists(source):
            continue
        try:
            final = copy_file(source, plan.target) if copy else move_file(source, plan.target)
        except OSError:
            continue
        result = Plan(source=plan.source, target=str(final), reason=plan.reason)
        done.append(result)
        if journal is not None:
            journal.record(op, src=plan.source, dst=str(final), copy=copy)
        if db is not None and not copy:
            db.move_path(plan.source, str(final))
    return done


def trash_paths(
    paths: list[str | os.PathLike[str]],
    *,
    data_dir: str | os.PathLike[str],
    db: Database | None = None,
    journal: Journal | None = None,
    dry_run: bool = True,
) -> list[tuple[str, str]]:
    """Move files into filekeep's own trash, recording where they came from."""
    trash_root = Path(data_dir).expanduser() / "trash"
    done: list[tuple[str, str]] = []
    for raw in paths:
        source = Path(raw)
        if not lexists(source):
            continue
        key = uuid.uuid4().hex[:12]
        destination = trash_root / key / source.name
        done.append((str(source), str(destination)))
        if dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = os.lstat(source).st_size
        except OSError:
            size = 0
        shutil.move(str(source), str(destination))
        entry_id = db.trash_add(str(source), str(destination), size) if db else 0
        if journal is not None:
            journal.record("trash", src=str(source), dst=str(destination), id=entry_id)
        if db is not None:
            db.delete_file(str(source))
    return done


def restore_paths(
    entries: list,
    *,
    db: Database | None = None,
    journal: Journal | None = None,
    dry_run: bool = True,
) -> list[tuple[str, str]]:
    """Move trashed files back to where they came from."""
    done: list[tuple[str, str]] = []
    for entry in entries:
        trashed = entry["trashed_path"]
        original = entry["original_path"]
        if not lexists(trashed):
            continue
        target = unique_path(original)
        done.append((trashed, str(target)))
        if dry_run:
            continue
        move_file(trashed, target)
        if db is not None:
            db.trash_mark_restored(int(entry["id"]))
        if journal is not None:
            journal.record("restore", src=trashed, dst=str(target), id=int(entry["id"]))
    return done


def undo(
    *,
    journal: Journal,
    db: Database | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    steps: int = 1,
    dry_run: bool = False,
) -> list[tuple[str, str, str]]:
    """Undo the last ``steps`` recorded operations. Returns ``(op, from, to)`` triples."""
    undone: list[tuple[str, str, str]] = []
    taken = journal.pop(steps) if not dry_run else list(reversed(journal.entries()[-steps:]))
    for entry in taken:
        op = str(entry.get("op", ""))
        source = str(entry.get("src", ""))
        target = str(entry.get("dst", ""))
        if op in {"move", "organize", "rename"}:
            if not lexists(target):
                undone.append((op, target, source))
                continue
            if dry_run:
                undone.append((op, target, source))
                continue
            final = move_file(target, source)
            if db is not None:
                db.move_path(target, str(final))
            undone.append((op, target, str(final)))
        elif op == "copy":
            if not dry_run and lexists(target):
                Path(target).unlink()
            undone.append((op, target, source))
        elif op == "trash":
            if dry_run:
                undone.append((op, target, source))
                continue
            if not lexists(target):
                continue
            final = move_file(target, source)
            if db is not None and entry.get("id"):
                db.trash_mark_restored(int(entry["id"]))
            undone.append((op, target, str(final)))
    return undone
