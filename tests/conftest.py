"""Shared fixtures: a small isolated tree, an index and a CLI runner."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from filekeep.db import Database
from filekeep.index import scan
from filekeep.journal import Journal


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point FILEKEEP_HOME at a temporary directory for every test."""
    home = tmp_path / "fkhome"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FILEKEEP_HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("filekeep.ui.supports_color", lambda *args, **kwargs: False)
    return home


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small directory tree with a duplicate pair and a few kinds."""
    root = tmp_path / "tree"
    (root / "photos").mkdir(parents=True)
    (root / "code" / "pkg").mkdir(parents=True)
    (root / "downloads").mkdir()
    (root / "photos" / "one.jpg").write_bytes(b"jpeg-payload")
    (root / "photos" / "one-copy.jpg").write_bytes(b"jpeg-payload")
    (root / "photos" / "two.png").write_bytes(b"png-payload")
    (root / "code" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "code" / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "downloads" / "archive.zip").write_bytes(b"zip-payload")
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    (root / "notes-copy.txt").write_text("hello\n", encoding="utf-8")
    return root


@pytest.fixture
def db(isolated_home: Path) -> Database:
    """An empty index inside the isolated home."""
    database = Database(isolated_home / "index.db")
    yield database
    database.close()


@pytest.fixture
def indexed(tree: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """An index already containing :func:`tree`."""
    monkeypatch.chdir(tree)
    database = Database()
    scan(database, [tree], hash_policy="always")
    yield database
    database.close()


@pytest.fixture
def journal() -> Journal:
    """A journal writing into the isolated home."""
    return Journal(Path(os.environ["FILEKEEP_HOME"]) / "journal.jsonl")


def symlink_or_skip(link: Path, target: str | Path) -> None:
    """Create a symlink, or skip the test where the platform does not allow it."""
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    except (OSError, NotImplementedError) as error:  # pragma: no cover - Windows without dev mode
        pytest.skip(f"symlinks are not available here: {error}")


def write(path: Path, content: bytes | str = "data") -> Path:
    """Create ``path`` (and parents) with ``content``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def make_row(
    path: Path,
    *,
    size: int = 10,
    mtime: float = 0.0,
    kind: str = "document",
    ext: str = "txt",
    hash_value: str = "abc",
):
    """Build a :class:`filekeep.db.FileRow` for plan tests without touching the index."""
    from filekeep.db import FileRow

    return FileRow(
        id=1,
        root=str(path.parent),
        path=str(path),
        name=path.name,
        ext=ext,
        kind=kind,
        size=size,
        mtime=mtime,
        is_link=False,
        hash=hash_value,
        indexed_at=mtime,
        missing=False,
    )
