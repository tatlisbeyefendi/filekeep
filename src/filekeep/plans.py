"""Turn filters into concrete plans: organising folders and renaming in bulk."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from filekeep.db import FileRow
from filekeep.fsops import Plan, unique_path
from filekeep.kinds import folder_for_kind

ORGANIZE_MODES = ("kind", "ext", "year", "month", "first-letter")
RENAME_TOKENS = ("stem", "name", "ext", "kind", "year", "month", "day", "n", "parent", "size")


def destination_for(row: FileRow, *, by: str, into: str | Path) -> Path:
    """Return where ``row`` belongs for ``filekeep organize --by <mode>``."""
    base = Path(into)
    if by == "kind":
        return base / folder_for_kind(row.kind) / row.name
    if by == "ext":
        return base / (row.ext or "_no-extension") / row.name
    stamp = datetime.fromtimestamp(row.mtime)
    if by == "year":
        return base / f"{stamp.year:04d}" / row.name
    if by == "month":
        return base / f"{stamp.year:04d}-{stamp.month:02d}" / row.name
    if by == "first-letter":
        letter = row.name[:1].upper()
        bucket = letter if letter.isalnum() else "_"
        return base / bucket / row.name
    raise ValueError(f"unknown organize mode: {by!r}")


def plan_organize(
    rows: list[FileRow],
    *,
    by: str,
    into: str | Path,
    copy: bool = False,
) -> list[Plan]:
    """Plan moving (or copying) ``rows`` into a rule-based folder tree."""
    base = str(Path(into).expanduser().resolve())
    plans: list[Plan] = []
    for row in rows:
        if row.path.startswith(base + "/"):
            continue
        target = destination_for(row, by=by, into=base)
        if str(target) == row.path:
            continue
        plans.append(Plan(source=row.path, target=str(target), reason=f"by {by}"))
    return plans


_TOKEN = re.compile(r"\{(\w+)\}")


def expand_pattern(
    pattern: str,
    row: FileRow,
    *,
    index: int = 0,
    pad: int | None = None,
    now: float | None = None,
) -> str:
    """Expand ``{stem}``-style tokens for one file."""
    stamp = datetime.fromtimestamp(row.mtime)
    stem = Path(row.name).stem
    values = {
        "stem": stem,
        "name": stem,
        "ext": row.ext,
        "kind": row.kind,
        "year": f"{stamp.year:04d}",
        "month": f"{stamp.month:02d}",
        "day": f"{stamp.day:02d}",
        "parent": Path(row.path).parent.name,
        "n": str(index).zfill(pad) if pad else str(index),
        "size": str(row.size),
    }
    unknown = [token for token in _TOKEN.findall(pattern) if token not in values]
    if unknown:
        raise ValueError(f"unknown token(s) in pattern: {', '.join(sorted(set(unknown)))}")
    return _TOKEN.sub(lambda match: values[match.group(1)], pattern)


def plan_rename(
    rows: list[FileRow],
    pattern: str,
    *,
    find: str | None = None,
    replace: str = "",
    keep_ext: bool = True,
    start: int = 1,
    pad: int | None = None,
    dry_run: bool = True,
) -> list[Plan]:
    """Plan renaming ``rows`` with a token pattern and an optional regex substitution."""
    plans: list[Plan] = []
    ordered = sorted(rows, key=lambda item: item.path)
    for position, row in enumerate(ordered, start=start):
        try:
            expanded = expand_pattern(pattern, row, index=position, pad=pad)
        except ValueError:
            raise
        if find:
            expanded = re.sub(find, replace, expanded)
        if keep_ext and row.ext:
            lowered = expanded.lower()
            if lowered.endswith("." + row.ext):
                pass
            elif lowered.endswith(row.ext):
                expanded = f"{expanded[: -len(row.ext)]}.{row.ext}"
            else:
                expanded = f"{expanded}.{row.ext}"
        if not expanded.strip():
            continue
        parent = Path(row.path).parent
        target = Path(expanded) if Path(expanded).is_absolute() else parent / expanded
        if str(target) == row.path:
            continue
        if not dry_run:
            target = unique_path(target)
        plans.append(Plan(source=row.path, target=str(target), reason="rename"))
    return plans


def plan_duplicates(groups: list[list[FileRow]], *, keep: str = "newest") -> list[Plan]:
    """Plan trashing every copy but the keeper in each duplicate group."""
    plans: list[Plan] = []
    for group in groups:
        if len(group) < 2:
            continue
        if keep == "oldest":
            keeper = min(group, key=lambda item: (item.mtime, len(item.path), item.path))
        elif keep == "shortest-path":
            keeper = min(group, key=lambda item: (len(item.path), item.path))
        elif keep == "first":
            keeper = min(group, key=lambda item: item.path)
        else:  # newest; on an mtime tie the shorter path wins, so "x.jpg" beats "x (copy).jpg"
            keeper = max(group, key=lambda item: (item.mtime, -len(item.path)))
        for row in group:
            if row.path != keeper.path:
                plans.append(
                    Plan(source=row.path, target=keeper.path, reason=f"duplicate of {keeper.path}")
                )
    return plans


def human_timestamp(moment: float | None = None) -> str:
    """``2026-10-30 14:02`` in local time."""
    return datetime.fromtimestamp(moment if moment is not None else time.time()).strftime(
        "%Y-%m-%d %H:%M"
    )


__all__ = [
    "ORGANIZE_MODES",
    "RENAME_TOKENS",
    "Plan",
    "destination_for",
    "expand_pattern",
    "human_timestamp",
    "plan_duplicates",
    "plan_organize",
    "plan_rename",
    "unique_path",
]
