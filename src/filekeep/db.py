"""SQLite storage for the file index, tags, trash and journal bookkeeping."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY,
    root       TEXT NOT NULL,
    path       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    ext        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    is_link    INTEGER NOT NULL DEFAULT 0,
    hash       TEXT,
    indexed_at REAL NOT NULL,
    missing    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS files_size ON files(size);
CREATE INDEX IF NOT EXISTS files_kind ON files(kind);
CREATE INDEX IF NOT EXISTS files_ext  ON files(ext);
CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS files_root ON files(root);

CREATE TABLE IF NOT EXISTS tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    added_at REAL NOT NULL,
    PRIMARY KEY (file_id, tag)
);

CREATE TABLE IF NOT EXISTS trash (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT NOT NULL,
    trashed_path  TEXT NOT NULL UNIQUE,
    size          INTEGER NOT NULL,
    deleted_at    REAL NOT NULL,
    restored_at   REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

FILE_COLUMNS = "id, root, path, name, ext, kind, size, mtime, is_link, hash, indexed_at, missing"


@dataclass(frozen=True)
class FileRow:
    """One indexed file."""

    id: int
    root: str
    path: str
    name: str
    ext: str
    kind: str
    size: int
    mtime: float
    is_link: bool
    hash: str | None
    indexed_at: float
    missing: bool

    def age(self, now: float | None = None) -> float:
        return max(0.0, (now if now is not None else time.time()) - self.mtime)


def default_data_dir() -> Path:
    """Return the per-user data directory (XDG aware)."""
    override = os.environ.get("FILEKEEP_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base).expanduser() / "filekeep"
    return Path.home() / ".local" / "share" / "filekeep"


def default_db_path() -> Path:
    """Default index location."""
    return default_data_dir() / "index.db"


class Database:
    """Thin wrapper around a SQLite connection holding the index."""

    def __init__(self, path: str | os.PathLike[str] | None = None, *, create: bool = True) -> None:
        self.path = Path(path).expanduser() if path else default_db_path()
        self._conn: sqlite3.Connection | None = None
        self._create = create

    # -- connection -----------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _connect(self) -> sqlite3.Connection:
        if not self.path.parent.exists():
            if not self._create:
                raise FileNotFoundError(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and not self._create:
            raise FileNotFoundError(self.path)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    # -- files ----------------------------------------------------------
    def upsert_files(self, records: Iterable[tuple]) -> int:
        """Insert or update file rows.

        Each record is ``(root, path, name, ext, kind, size, mtime, is_link[, hash])``.
        """
        rows = [
            (
                record[0],
                record[1],
                record[2],
                record[3],
                record[4],
                record[5],
                record[6],
                int(record[7]),
                record[8] if len(record) > 8 else None,
                time.time(),
            )
            for record in records
        ]
        if not rows:
            return 0
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO files(root, path, name, ext, kind, size, mtime, is_link, hash, "
                "indexed_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "  root=excluded.root, name=excluded.name, ext=excluded.ext, kind=excluded.kind, "
                "  size=excluded.size, mtime=excluded.mtime, is_link=excluded.is_link, "
                "  hash=COALESCE(excluded.hash, files.hash), "
                "  indexed_at=excluded.indexed_at, missing=0",
                rows,
            )
        return len(rows)

    def by_path(self, path: str) -> FileRow | None:
        row = self.conn.execute(
            f"SELECT {FILE_COLUMNS} FROM files WHERE path = ?", (path,)
        ).fetchone()
        return _to_row(row)

    def by_id(self, file_id: int) -> FileRow | None:
        row = self.conn.execute(
            f"SELECT {FILE_COLUMNS} FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        return _to_row(row)

    def update_hash(self, path: str, digest: str | None) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE files SET hash = ?, indexed_at = ? WHERE path = ?",
                (digest, time.time(), path),
            )

    def set_missing(self, paths: Sequence[str]) -> int:
        if not paths:
            return 0
        with self.transaction() as conn:
            cursor = conn.executemany(
                "UPDATE files SET missing = 1 WHERE path = ?", [(path,) for path in paths]
            )
            return cursor.rowcount or 0

    def prune_root(self, root: str, keep: Iterable[str]) -> int:
        """Delete rows under ``root`` whose path is not in ``keep``."""
        keep = set(keep)
        with self.transaction() as conn:
            stale = [
                row["path"]
                for row in conn.execute("SELECT path FROM files WHERE root = ?", (root,))
                if row["path"] not in keep
            ]
            conn.executemany("DELETE FROM files WHERE path = ?", [(path,) for path in stale])
        return len(stale)

    def delete_file(self, path: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def move_path(self, source: str, destination: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE files SET path = ?, name = ? WHERE path = ?",
                (
                    destination,
                    Path(destination).name,
                    source,
                ),
            )

    def count(self, *, include_missing: bool = False) -> int:
        clause = "" if include_missing else " WHERE missing = 0"
        return int(self.conn.execute(f"SELECT COUNT(*) FROM files{clause}").fetchone()[0])

    def roots(self) -> list[str]:
        return [
            row[0] for row in self.conn.execute("SELECT DISTINCT root FROM files ORDER BY root")
        ]

    # -- tags -----------------------------------------------------------
    def add_tag(self, path: str, tag: str) -> bool:
        row = self.by_path(path)
        if row is None:
            raise KeyError(path)
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tags(file_id, tag, added_at) VALUES(?, ?, ?)",
                (row.id, tag, time.time()),
            )
            return bool(cursor.rowcount)

    def remove_tag(self, path: str, tag: str) -> bool:
        row = self.by_path(path)
        if row is None:
            raise KeyError(path)
        with self.transaction() as conn:
            cursor = conn.execute("DELETE FROM tags WHERE file_id = ? AND tag = ?", (row.id, tag))
            return bool(cursor.rowcount)

    def tags_for(self, file_id: int) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT tag FROM tags WHERE file_id = ? ORDER BY tag", (file_id,)
            )
        ]

    def all_tags(self) -> list[tuple[str, int]]:
        return [
            (row[0], row[1])
            for row in self.conn.execute("SELECT tag, COUNT(*) FROM tags GROUP BY tag ORDER BY tag")
        ]

    # -- trash ----------------------------------------------------------
    def trash_add(self, original_path: str, trashed_path: str, size: int) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO trash(original_path, trashed_path, size, deleted_at) "
                "VALUES(?, ?, ?, ?)",
                (original_path, trashed_path, size, time.time()),
            )
            return int(cursor.lastrowid or 0)

    def trash_entries(self, *, include_restored: bool = False) -> list[sqlite3.Row]:
        clause = "" if include_restored else " WHERE restored_at IS NULL"
        return list(
            self.conn.execute(f"SELECT * FROM trash{clause} ORDER BY deleted_at DESC, id DESC")
        )

    def trash_get(self, entry_id: int) -> sqlite3.Row | None:
        cursor = self.conn.execute("SELECT * FROM trash WHERE id = ?", (entry_id,))
        return cursor.fetchone()

    def trash_mark_restored(self, entry_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE trash SET restored_at = ? WHERE id = ?", (time.time(), entry_id))

    # -- meta -----------------------------------------------------------
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def _to_row(row: sqlite3.Row | None) -> FileRow | None:
    if row is None:
        return None
    return FileRow(
        id=row["id"],
        root=row["root"],
        path=row["path"],
        name=row["name"],
        ext=row["ext"],
        kind=row["kind"],
        size=row["size"],
        mtime=row["mtime"],
        is_link=bool(row["is_link"]),
        hash=row["hash"],
        indexed_at=row["indexed_at"],
        missing=bool(row["missing"]),
    )
