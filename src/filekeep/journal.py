"""An append-only JSONL log of every change filekeep makes, so it can be undone."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

UNDOABLE = ("move", "rename", "organize", "trash", "copy")


class Journal:
    """Records operations and lets :mod:`filekeep.fsops` reverse them."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser()

    def record(self, op: str, **fields: Any) -> dict[str, Any]:
        entry = {"ts": time.time(), "op": op, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:  # pragma: no cover - corrupt line
                    continue
        return result

    def count(self) -> int:
        return len(self.entries())

    def tail(self, count: int = 10) -> list[dict[str, Any]]:
        entries = self.entries()
        return entries[-count:] if count > 0 else []

    def pop(self, count: int = 1) -> list[dict[str, Any]]:
        """Remove and return the last ``count`` entries, newest first."""
        entries = self.entries()
        if not entries:
            return []
        count = max(1, min(count, len(entries)))
        taken = entries[-count:]
        remaining = entries[:-count]
        self._rewrite(remaining)
        return list(reversed(taken))

    def _rewrite(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def is_empty(self) -> bool:
        return not self.path.exists() or self.path.stat().st_size == 0
