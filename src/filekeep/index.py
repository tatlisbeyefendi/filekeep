"""Walk the filesystem, hash files and keep the SQLite index up to date."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from filekeep.db import Database
from filekeep.kinds import ext_of, kind_for

DEFAULT_MAX_HASH_SIZE = 256 * 1024 * 1024  # 256 MiB
CHUNK_SIZE = 1024 * 1024

HASH_POLICIES = ("auto", "always", "never")


@dataclass(frozen=True)
class Entry:
    """A single filesystem object discovered by :func:`walk`."""

    root: str
    path: str
    name: str
    ext: str
    kind: str
    size: int
    mtime: float
    is_link: bool

    def record(self, digest: str | None = None) -> tuple:
        base = (
            self.root,
            self.path,
            self.name,
            self.ext,
            self.kind,
            self.size,
            self.mtime,
            self.is_link,
        )
        return base if digest is None else (*base, digest)


@dataclass
class ScanResult:
    """What a scan accomplished."""

    roots: list[str] = field(default_factory=list)
    files: int = 0
    dirs: int = 0
    hashed: int = 0
    skipped: int = 0
    pruned: int = 0
    bytes: int = 0
    elapsed: float = 0.0

    @property
    def hashed_bytes(self) -> int:  # pragma: no cover - convenience
        return self.bytes


def hash_file(path: str | os.PathLike[str], *, limit: int | None = None) -> str | None:
    """Return the SHA-256 of ``path`` in hex, or ``None`` when it cannot be read."""
    digest = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                read += len(chunk)
                if limit is not None and read > limit:
                    return None
    except OSError:
        return None
    return digest.hexdigest()


def walk(
    root: str | os.PathLike[str],
    *,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    exclude: Iterable[str] = (),
    skip_paths: Iterable[str] = (),
    counters: dict[str, int] | None = None,
) -> Iterator[Entry]:
    """Yield :class:`Entry` objects below ``root`` (depth-first, no sorting guarantees)."""
    root_path = Path(root).expanduser()
    try:
        root_resolved = str(root_path.resolve())
    except OSError:  # pragma: no cover - unreadable root
        return
    excluded = {name.lower() for name in exclude}
    skipped = {str(Path(item)) for item in skip_paths}
    stack: list[tuple[Path, bool]] = [(root_path, False)]

    while stack:
        directory, is_link = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for item in entries:
            name = item.name
            path = str(Path(item.path))
            if path in skipped:
                continue
            if not include_hidden and name.startswith("."):
                continue
            is_link = item.is_symlink()
            try:
                points_to_dir = item.is_dir(follow_symlinks=True)
            except OSError:
                continue
            if points_to_dir:
                if is_link and not follow_symlinks:
                    continue
                if excluded and name.lower() in excluded:
                    continue
                stack.append((Path(item.path), is_link))
                if counters is not None:
                    counters["dirs"] = counters.get("dirs", 0) + 1
                continue
            if not is_link and not item.is_file(follow_symlinks=False):
                # sockets, fifos and devices are not files for our purposes
                continue
            try:
                stat = item.stat(follow_symlinks=True)
                size = int(stat.st_size)
                mtime = float(stat.st_mtime)
            except OSError:
                # a broken symlink: keep it visible so `doctor` can report it, and use the
                # link's own timestamp instead of pretending it is from 1970
                try:
                    stat = item.stat(follow_symlinks=False)
                    size = 0
                    mtime = float(stat.st_mtime)
                except OSError:
                    size, mtime = 0, 0.0
            ext = ext_of(name)
            yield Entry(
                root=root_resolved,
                path=path,
                name=name,
                ext=ext,
                kind=kind_for(ext),
                size=size,
                mtime=mtime,
                is_link=is_link,
            )


def _internal_paths(db: Database) -> set[str]:
    """Paths belonging to filekeep itself: never index our own index, trash or journal."""
    data_dir = db.path.parent
    skip = {str(db.path)}
    skip.update(f"{db.path}{suffix}" for suffix in ("-wal", "-shm", "-journal"))
    skip.add(str(data_dir / "trash"))
    skip.add(str(data_dir / "journal.jsonl"))
    return skip


def _needs_hash(
    entry: Entry,
    existing_hash: str | None,
    existing_size: int,
    existing_mtime: float,
    policy: str,
    max_size: int,
) -> bool:
    if policy == "never":
        return False
    if (
        existing_hash is not None
        and existing_size == entry.size
        and abs(existing_mtime - entry.mtime) < 1e-6
    ):
        return False
    if policy == "always":
        return True
    return entry.size <= max_size


def scan(
    db: Database,
    roots: Iterable[str | os.PathLike[str]],
    *,
    hash_policy: str = "auto",
    jobs: int = 8,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    exclude: Iterable[str] = (),
    prune: bool = True,
    max_hash_size: int = DEFAULT_MAX_HASH_SIZE,
) -> ScanResult:
    """Index every file below ``roots`` into ``db``."""
    if hash_policy not in HASH_POLICIES:
        raise ValueError(f"unknown hash policy: {hash_policy!r}")
    started = time.monotonic()
    result = ScanResult()
    seen: dict[str, set[str]] = {}
    batches: list[tuple] = []
    pending: list[Entry] = []
    counters: dict[str, int] = {"dirs": 0}
    skip = _internal_paths(db)

    for root in roots:
        root_path = Path(root).expanduser()
        resolved = str(root_path.resolve())
        result.roots.append(resolved)
        seen[resolved] = set()
        for entry in walk(
            root_path,
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            exclude=exclude,
            skip_paths=skip,
            counters=counters,
        ):
            seen[resolved].add(entry.path)
            result.files += 1
            result.bytes += entry.size
            existing = db.by_path(entry.path)
            if _needs_hash(
                entry,
                existing.hash if existing else None,
                existing.size if existing else -1,
                existing.mtime if existing else -1.0,
                hash_policy,
                max_hash_size,
            ):
                pending.append(entry)
            else:
                batches.append(entry.record(existing.hash if existing else None))

    digests: dict[str, str | None] = {}
    if pending:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for entry, digest in zip(
                pending, pool.map(lambda item: hash_file(item.path), pending), strict=True
            ):
                digests[entry.path] = digest
                if digest is not None:
                    result.hashed += 1
                else:
                    result.skipped += 1
        for entry in pending:
            batches.append(entry.record(digests.get(entry.path)))

    result.dirs = counters["dirs"]

    db.upsert_files(batches)
    if prune:
        for root, paths in seen.items():
            result.pruned += db.prune_root(root, paths)
    result.elapsed = time.monotonic() - started
    db.meta_set("last_scan", str(time.time()))
    db.meta_set("last_scan_roots", os.pathsep.join(result.roots))
    return result
