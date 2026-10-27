"""Filtering, sorting and statistics over the index."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from filekeep.db import FILE_COLUMNS, Database, FileRow

SORTS = ("path", "name", "size", "age", "kind", "ext")
SORT_COLUMNS = {
    "path": ("path", "ASC"),
    "name": ("name", "ASC"),
    "size": ("size", "DESC"),
    "age": ("mtime", "ASC"),
    "kind": ("kind", "ASC"),
    "ext": ("ext", "ASC"),
}


def order_clause(sort: str, reverse: bool = False) -> str:
    """Return the ``ORDER BY`` body for ``sort``, flipped when ``reverse`` is set."""
    column, direction = SORT_COLUMNS.get(sort, SORT_COLUMNS["path"])
    if reverse:
        direction = "DESC" if direction == "ASC" else "ASC"
    tiebreak = "path ASC" if column != "path" else "path DESC"
    return f"{column} {direction}, {tiebreak}"


@dataclass
class FileFilter:
    """Every way the CLI can narrow the index down."""

    roots: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    exts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    name_like: str | None = None
    name_glob: str | None = None
    name_regex: str | None = None
    path_like: str | None = None
    min_size: int | None = None
    max_size: int | None = None
    older_than: float | None = None
    newer_than: float | None = None
    include_missing: bool = False
    include_links: bool = True

    def build(self, now: float | None = None) -> tuple[str, list[Any]]:
        """Return the WHERE clause and its parameters."""
        now = time.time() if now is None else now
        clauses: list[str] = []
        params: list[Any] = []

        if not self.include_missing:
            clauses.append("missing = 0")
        if not self.include_links:
            clauses.append("is_link = 0")
        if self.roots:
            clauses.append("(" + " OR ".join("path LIKE ?" for _ in self.roots) + ")")
            params.extend(f"{root.rstrip('/')}/%" for root in self.roots)
        if self.kinds:
            clauses.append("kind IN (" + ",".join("?" for _ in self.kinds) + ")")
            params.extend(self.kinds)
        if self.exts:
            clauses.append("ext IN (" + ",".join("?" for _ in self.exts) + ")")
            params.extend(self.exts)
        if self.tags:
            for tag in self.tags:
                clauses.append("id IN (SELECT file_id FROM tags WHERE tag = ?)")
                params.append(tag)
        if self.name_like is not None:
            clauses.append("name LIKE ?")
            params.append(f"%{self.name_like}%")
        if self.path_like is not None:
            clauses.append("path LIKE ?")
            params.append(f"%{self.path_like}%")
        if self.min_size is not None:
            clauses.append("size >= ?")
            params.append(int(self.min_size))
        if self.max_size is not None:
            clauses.append("size <= ?")
            params.append(int(self.max_size))
        if self.older_than is not None:
            clauses.append("mtime <= ?")
            params.append(now - self.older_than)
        if self.newer_than is not None:
            clauses.append("mtime >= ?")
            params.append(now - self.newer_than)

        return (" AND ".join(clauses) or "1=1"), params

    def matches_regex(self, path: str) -> bool:
        if not self.name_regex:
            return True
        return re.search(self.name_regex, path) is not None

    def matches_glob(self, path: str) -> bool:
        if not self.name_glob:
            return True
        from fnmatch import fnmatch

        return fnmatch(path, self.name_glob) or fnmatch(path.rsplit("/", 1)[-1], self.name_glob)


def search(
    db: Database,
    spec: FileFilter | None = None,
    *,
    sort: str = "path",
    reverse: bool = False,
    limit: int | None = None,
    now: float | None = None,
) -> list[FileRow]:
    """Query the index and return matching rows."""
    spec = spec or FileFilter()
    clause, params = spec.build(now)
    order = order_clause(sort, reverse)
    sql = f"SELECT {FILE_COLUMNS} FROM files WHERE {clause} ORDER BY {order}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = [_row(row) for row in db.conn.execute(sql, params)]
    if spec.name_regex:
        rows = [row for row in rows if spec.matches_regex(row.name)]
    if spec.name_glob:
        rows = [row for row in rows if spec.matches_glob(row.path)]
    return rows


def _row(row: Any) -> FileRow:
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


def duplicate_groups(
    db: Database,
    *,
    min_size: int = 1,
    max_groups: int | None = None,
    spec: FileFilter | None = None,
) -> list[list[FileRow]]:
    """Return groups of files that share a size and a SHA-256 digest."""
    spec = spec or FileFilter()
    clause, params = spec.build()
    candidates = [
        _row(row)
        for row in db.conn.execute(
            f"SELECT {FILE_COLUMNS} FROM files "
            f"WHERE {clause} AND size >= ? AND hash IS NOT NULL "
            "ORDER BY size DESC, path ASC",
            [*params, int(min_size)],
        )
    ]
    buckets: dict[tuple[int, str], list[FileRow]] = {}
    for row in candidates:
        buckets.setdefault((row.size, row.hash or ""), []).append(row)
    groups = [
        sorted(group, key=lambda item: item.path) for group in buckets.values() if len(group) > 1
    ]
    groups.sort(key=lambda group: group[0].size * (len(group) - 1), reverse=True)
    if max_groups is not None:
        groups = groups[:max_groups]
    return groups


def unhashed(db: Database, *, min_size: int = 1) -> list[FileRow]:
    """Rows that still have no digest (needed before a duplicate search can be trusted)."""
    return [
        _row(row)
        for row in db.conn.execute(
            f"SELECT {FILE_COLUMNS} FROM files "
            "WHERE hash IS NULL AND missing = 0 AND size >= ? "
            "ORDER BY size DESC",
            (int(min_size),),
        )
    ]


@dataclass
class KindStat:
    kind: str
    files: int
    size: int


@dataclass
class Stats:
    files: int
    size: int
    kinds: list[KindStat]
    years: dict[str, tuple[int, int]]
    oldest: FileRow | None
    newest: FileRow | None
    missing: int


def stats(db: Database) -> Stats:
    """Aggregate counts and sizes for ``filekeep stats``."""
    kinds = [
        KindStat(kind=row["kind"], files=row["files"], size=row["size"])
        for row in db.conn.execute(
            "SELECT kind, COUNT(*) AS files, SUM(size) AS size FROM files "
            "WHERE missing = 0 GROUP BY kind ORDER BY size DESC"
        )
    ]
    years = {
        str(row["year"]): (row["files"], row["size"])
        for row in db.conn.execute(
            "SELECT strftime('%Y', mtime, 'unixepoch') AS year, COUNT(*) AS files, "
            "SUM(size) AS size FROM files WHERE missing = 0 GROUP BY year ORDER BY year"
        )
    }
    totals = db.conn.execute(
        "SELECT COUNT(*) AS files, COALESCE(SUM(size), 0) AS size FROM files WHERE missing = 0"
    ).fetchone()
    oldest = db.conn.execute(
        f"SELECT {FILE_COLUMNS} FROM files WHERE missing = 0 ORDER BY mtime ASC LIMIT 1"
    ).fetchone()
    newest = db.conn.execute(
        f"SELECT {FILE_COLUMNS} FROM files WHERE missing = 0 ORDER BY mtime DESC LIMIT 1"
    ).fetchone()
    missing = int(db.conn.execute("SELECT COUNT(*) FROM files WHERE missing = 1").fetchone()[0])
    return Stats(
        files=int(totals["files"]),
        size=int(totals["size"]),
        kinds=kinds,
        years=years,
        oldest=_row(oldest) if oldest else None,
        newest=_row(newest) if newest else None,
        missing=missing,
    )
