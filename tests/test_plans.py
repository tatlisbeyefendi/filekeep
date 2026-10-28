"""Organising and renaming plans."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from filekeep.db import FileRow
from filekeep.plans import (
    ORGANIZE_MODES,
    expand_pattern,
    plan_duplicates,
    plan_organize,
    plan_rename,
)

from .conftest import make_row


def row_at(
    tmp_path: Path, name: str, *, mtime: float = 0.0, kind: str = "image", size: int = 10
) -> FileRow:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return make_row(tmp_path / name, mtime=mtime, kind=kind, ext=ext, size=size)


@pytest.mark.parametrize("mode", ORGANIZE_MODES)
def test_organize_modes_produce_paths(tmp_path: Path, mode: str) -> None:
    row = row_at(tmp_path, "photo.jpg", mtime=1_700_000_000.0)
    plans = plan_organize([row], by=mode, into=tmp_path / "sorted")
    assert len(plans) == 1
    assert plans[0].target.startswith(str(tmp_path / "sorted"))
    assert plans[0].target.endswith("photo.jpg")


def test_organize_by_kind_uses_folder_names(tmp_path: Path) -> None:
    rows = [
        row_at(tmp_path, "a.jpg", kind="image"),
        row_at(tmp_path, "b.mp4", kind="video"),
        row_at(tmp_path, "c.xlsx", kind="sheet"),
    ]
    targets = [
        Path(plan.target).parent.name
        for plan in plan_organize(rows, by="kind", into=tmp_path / "s")
    ]
    assert targets == ["Photos", "Videos", "Spreadsheets"]


def test_organize_by_ext(tmp_path: Path) -> None:
    rows = [row_at(tmp_path, "a.jpg"), row_at(tmp_path, "README", kind="other")]
    targets = [
        Path(plan.target).parent.name for plan in plan_organize(rows, by="ext", into=tmp_path / "s")
    ]
    assert targets == ["jpg", "_no-extension"]


def test_organize_by_year_and_month(tmp_path: Path) -> None:
    moment = time.mktime((2021, 6, 15, 12, 0, 0, 0, 0, -1))
    row = row_at(tmp_path, "a.txt", mtime=moment)
    by_year = plan_organize([row], by="year", into=tmp_path / "s")
    by_month = plan_organize([row], by="month", into=tmp_path / "s")
    assert Path(by_year[0].target).parent.name == "2021"
    assert Path(by_month[0].target).parent.name == "2021-06"


def test_organize_by_first_letter(tmp_path: Path) -> None:
    rows = [row_at(tmp_path, "alpha.txt"), row_at(tmp_path, "123.txt")]
    targets = [
        Path(plan.target).parent.name
        for plan in plan_organize(rows, by="first-letter", into=tmp_path / "s")
    ]
    assert targets == ["A", "1"]


def test_organize_skips_files_already_inside(tmp_path: Path) -> None:
    inside = tmp_path / "sorted" / "Photos"
    row = make_row(inside / "a.jpg", kind="image", ext="jpg")
    assert plan_organize([row], by="kind", into=tmp_path / "sorted") == []


def test_organize_rejects_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        plan_organize([row_at(tmp_path, "a.jpg")], by="colour", into=tmp_path / "s")


def test_expand_pattern_tokens(tmp_path: Path) -> None:
    moment = time.mktime((2020, 3, 4, 0, 0, 0, 0, 0, -1))
    row = row_at(tmp_path / "parent", "IMG_1.JPG", mtime=moment)
    expanded = expand_pattern(
        "{parent}/{year}-{month}-{day}/{n}-{kind}-{stem}-{size}.{ext}", row, index=7, pad=3
    )
    assert expanded == "parent/2020-03-04/007-image-IMG_1-10.jpg"


def test_expand_pattern_pads_only_with_pad(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.txt")
    assert expand_pattern("{n}", row, index=5) == "5"
    assert expand_pattern("{n}", row, index=5, pad=2) == "05"


def test_expand_pattern_rejects_unknown_token(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.txt")
    with pytest.raises(ValueError, match="unknown token"):
        expand_pattern("{magic}", row)


def test_rename_adds_extension(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    plans = plan_rename([row], "{stem}-new", dry_run=True)
    assert Path(plans[0].target).name == "a-new.jpg"


def test_rename_keeps_single_extension(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    assert plan_rename([row], "{stem}{ext}", dry_run=True) == []  # already correct → no plan


def test_rename_inserts_missing_dot(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    plans = plan_rename([row], "{stem}-x{ext}", dry_run=True)
    assert Path(plans[0].target).name == "a-x.jpg"


def test_rename_no_keep_ext(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    plans = plan_rename([row], "{stem}-bare", keep_ext=False, dry_run=True)
    assert Path(plans[0].target).name == "a-bare"


def test_rename_with_find_replace(tmp_path: Path) -> None:
    row = row_at(tmp_path, "IMG_2020.jpg")
    plans = plan_rename([row], "{stem}{ext}", find=r"^IMG_", replace="photo-", dry_run=True)
    assert Path(plans[0].target).name == "photo-2020.jpg"


def test_rename_sequence(tmp_path: Path) -> None:
    rows = [row_at(tmp_path, "b.jpg"), row_at(tmp_path, "a.jpg")]
    plans = plan_rename(rows, "{n}{ext}", start=1, pad=2, dry_run=True)
    assert [Path(plan.target).name for plan in plans] == ["01.jpg", "02.jpg"]


def test_rename_skips_unchanged(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    assert plan_rename([row], "{stem}{ext}", dry_run=True) == []


def test_rename_creates_subdirectories(tmp_path: Path) -> None:
    row = row_at(tmp_path, "a.jpg")
    plans = plan_rename([row], "{kind}/{stem}{ext}", dry_run=True)
    assert Path(plans[0].target).parent.name == "image"


def test_rename_avoids_collision_on_disk(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    first.write_bytes(b"1")
    (tmp_path / "b.jpg").write_bytes(b"2")
    row = make_row(first, kind="image", ext="jpg")
    plans = plan_rename([row], "b{ext}", dry_run=False)
    assert Path(plans[0].target).name == "b (2).jpg"


def test_plan_duplicates_keep_newest(tmp_path: Path) -> None:
    old = row_at(tmp_path, "old.txt", mtime=100.0, kind="document")
    new = row_at(tmp_path, "new.txt", mtime=200.0, kind="document")
    plans = plan_duplicates([[old, new]], keep="newest")
    assert [Path(plan.source).name for plan in plans] == ["old.txt"]


def test_plan_duplicates_keep_oldest(tmp_path: Path) -> None:
    old = row_at(tmp_path, "old.txt", mtime=100.0, kind="document")
    new = row_at(tmp_path, "new.txt", mtime=200.0, kind="document")
    plans = plan_duplicates([[old, new]], keep="oldest")
    assert [Path(plan.source).name for plan in plans] == ["new.txt"]


def test_plan_duplicates_keep_shortest_path(tmp_path: Path) -> None:
    short = make_row(tmp_path / "a" / "f.txt", kind="document", ext="txt")
    long = make_row(tmp_path / "a" / "b" / "c" / "f.txt", kind="document", ext="txt")
    plans = plan_duplicates([[long, short]], keep="shortest-path")
    assert [Path(plan.source).name for plan in plans] == ["f.txt"]
    assert str(tmp_path / "a" / "b") in plans[0].source or "c" in plans[0].source


def test_plan_duplicates_newest_tie_prefers_shorter_path(tmp_path: Path) -> None:
    plain = row_at(tmp_path, "photo.jpg", mtime=500.0, kind="image")
    copy = row_at(tmp_path, "photo (copy).jpg", mtime=500.0, kind="image")
    plans = plan_duplicates([[copy, plain]], keep="newest")
    assert [Path(plan.source).name for plan in plans] == ["photo (copy).jpg"]


def test_plan_duplicates_ignores_singletons(tmp_path: Path) -> None:
    row = row_at(tmp_path, "only.txt", kind="document")
    assert plan_duplicates([[row]]) == []
