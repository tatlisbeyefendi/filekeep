"""End to end tests for the command line interface."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from filekeep.cli import build_parser, main


def run(*args: str, capsys=None) -> tuple[int, str]:
    code = main(list(args))
    out = capsys.readouterr() if capsys is not None else None
    return code, (out.out if out else "")


def scan_tree(tree: Path, capsys) -> None:
    code = main(["--color", "never", "scan", str(tree), "--hash", "always"])
    capsys.readouterr()
    assert code == 0


def test_version(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "filekeep" in capsys.readouterr().out


def test_no_command_prints_help(capsys) -> None:
    assert main([]) == 0
    assert "usage: filekeep" in capsys.readouterr().out


def test_scan_reports_counts(tree: Path, capsys) -> None:
    code = main(["--color", "never", "scan", str(tree), "--hash", "always"])
    out = capsys.readouterr().out
    assert code == 0
    assert "indexed 8 files" in out
    assert "4 directories" in out


def test_scan_without_paths_reuses_last_roots(tree: Path, capsys) -> None:
    main(["--color", "never", "scan", str(tree)])
    capsys.readouterr()
    assert main(["--color", "never", "scan"]) == 0
    assert "indexed 8 files" in capsys.readouterr().out


def test_scan_without_paths_and_no_index(capsys) -> None:
    assert main(["--color", "never", "scan"]) == 1
    assert "nothing to scan" in capsys.readouterr().out


def test_scan_missing_directory(capsys, tmp_path: Path) -> None:
    assert main(["--color", "never", "scan", str(tmp_path / "nope")]) == 1
    assert "no such directory" in capsys.readouterr().out


def test_scan_skips_one_missing_root(tree: Path, capsys, tmp_path: Path) -> None:
    code = main(["--color", "never", "scan", str(tree), str(tmp_path / "nope")])
    out = capsys.readouterr().out
    assert code == 0
    assert "skipping missing directory" in out


def test_scan_json(tree: Path, capsys) -> None:
    main(["--json", "scan", str(tree), "--no-prune"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "scan"
    assert payload["files"] == 8
    assert payload["tool"] == "filekeep"


def test_scan_without_index_before_any_command(capsys) -> None:
    assert main(["--color", "never", "ls"]) == 1
    assert "no index yet" in capsys.readouterr().err


def test_ls_lists_files(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["--color", "never", "ls"]) == 0
    out = capsys.readouterr().out
    assert "one.jpg" in out
    assert "8 files" in out


def test_ls_filters_by_kind(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "ls", "--kind", "image"])
    out = capsys.readouterr().out
    assert "one.jpg" in out
    assert "app.py" not in out


def test_ls_filters_by_size(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "ls", "--min-size", "1KB"])
    assert "no files matched" in capsys.readouterr().out


def test_ls_long_shows_tags(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["tag", "add", str(tree / "notes.txt"), "keep"])
    capsys.readouterr()
    main(["--color", "never", "ls", "-v", "--tag", "keep"])
    out = capsys.readouterr().out
    assert "TAGS" in out
    assert "notes.txt" in out


def test_ls_empty_index_message(tree: Path, capsys) -> None:
    main(["--color", "never", "scan", str(tree), "--hash", "never"])
    capsys.readouterr()
    main(["--color", "never", "ls", "--kind", "font"])
    assert "no files matched" in capsys.readouterr().out


def test_ls_json(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--json", "ls", "--kind", "image"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 3
    assert {"path", "size", "kind"} <= set(payload["files"][0])


def test_find(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "find", "copy"])
    out = capsys.readouterr().out
    assert "one-copy.jpg" in out
    assert "notes-copy.txt" in out


def test_find_without_match(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "find", "zzz"])
    assert "no file matching" in capsys.readouterr().out


def test_find_glob(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "find", "unused", "--glob", "*.py"])
    out = capsys.readouterr().out
    assert "app.py" in out


def test_dupes_lists_groups(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["--color", "never", "dupes"]) == 0
    out = capsys.readouterr().out
    assert "group 1" in out
    assert "keep" in out and "trash" in out


def test_dupes_none_found(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "dupes", "--kind", "code"])
    assert "no duplicates found" in capsys.readouterr().out


def test_dupes_apply_trashes_copies(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "dupes", "--keep", "first", "--apply"])
    out = capsys.readouterr().out
    assert "trashed 2 copies" in out
    # "one-copy.jpg" sorts before "one.jpg", so the plain copy is the one removed
    assert not (tree / "photos" / "one.jpg").exists()
    assert (tree / "photos" / "one-copy.jpg").exists()
    assert not (tree / "notes.txt").exists()
    main(["--color", "never", "restore", "--list"])
    out = capsys.readouterr().out
    assert "one.jpg" in out
    assert "notes.txt" in out


def test_dupes_hashes_missing_candidates(tree: Path, capsys) -> None:
    main(["--color", "never", "scan", str(tree), "--hash", "never"])
    capsys.readouterr()
    assert main(["--color", "never", "dupes"]) == 0
    out = capsys.readouterr().out
    assert "group" in out


def test_dupes_json(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--json", "dupes"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["groups"]
    assert payload["reclaimable"] > 0


def test_big(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "big", "-l", "2"])
    out = capsys.readouterr().out
    assert "one.jpg" in out or "app.py" in out


def test_usage(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "usage", str(tree)])
    out = capsys.readouterr().out
    assert "photos" in out
    assert "DIRECTORY" in out


def test_usage_of_empty_filter(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "usage", str(tree / "code")])
    assert "DIRECTORY" in capsys.readouterr().out


def test_stale(tree: Path, capsys) -> None:
    old = tree / "notes.txt"
    os.utime(old, (0, 0))
    scan_tree(tree, capsys)
    main(["--color", "never", "stale", "--older-than", "1d"])
    out = capsys.readouterr().out
    assert "notes.txt" in out


def test_stale_nothing_found(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "stale", "--older-than", "100y"])
    assert "nothing that old" in capsys.readouterr().out


def test_organize_dry_run_then_apply(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    into = tree.parent / "sorted"
    main(["--color", "never", "organize", str(tree), "--by", "kind", "--into", str(into)])
    assert "dry run" in capsys.readouterr().out
    assert not into.exists()

    main(
        ["--color", "never", "organize", str(tree), "--by", "kind", "--into", str(into), "--apply"]
    )
    assert "moved 8 files" in capsys.readouterr().out
    assert (into / "Photos" / "one.jpg").exists()
    assert not (tree / "photos" / "one.jpg").exists()


def test_organize_copy(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    into = tree.parent / "copy"
    main(["--color", "never", "organize", str(tree), "--into", str(into), "--copy", "--apply"])
    capsys.readouterr()
    assert (into / "Photos" / "one.jpg").exists()
    assert (tree / "photos" / "one.jpg").exists()


def test_organize_nothing_to_do(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "organize", str(tree / "nope"), "--into", str(tree / "x")])
    assert "nothing to move" in capsys.readouterr().out


def test_rename_dry_run_then_apply(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(
        [
            "--color",
            "never",
            "rename",
            str(tree / "photos"),
            "--pattern",
            "photo-{n}{ext}",
            "--pad",
            "2",
        ]
    )
    assert "would be renamed" in capsys.readouterr().out
    main(
        [
            "--color",
            "never",
            "rename",
            str(tree / "photos"),
            "--pattern",
            "photo-{n}{ext}",
            "--pad",
            "2",
            "--apply",
        ]
    )
    assert "renamed 3 files" in capsys.readouterr().out
    assert (tree / "photos" / "photo-01.jpg").exists()


def test_rename_nothing_to_do(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "rename", str(tree), "--pattern", "{stem}{ext}"])
    assert "nothing to rename" in capsys.readouterr().out


def test_rename_bad_token(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["--color", "never", "rename", str(tree), "--pattern", "{bogus}"]) == 1
    assert "unknown token" in capsys.readouterr().out


def test_rename_json(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--json", "rename", str(tree / "photos"), "--pattern", "p{ext}"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["renames"]


def test_tag_add_remove_and_list(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["tag", "add", str(tree / "notes.txt"), "keep", "work"]) == 0
    out = capsys.readouterr().out
    assert "added keep" in out
    main(["--color", "never", "tag", "ls"])
    assert "work" in capsys.readouterr().out
    main(["tag", "rm", str(tree / "notes.txt"), "keep"])
    assert "removed keep" in capsys.readouterr().out
    main(["--color", "never", "tag", "ls"])
    assert "keep" not in capsys.readouterr().out


def test_tag_unknown_file(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["tag", "add", "/definitely/not/indexed", "x"]) == 1
    assert "not in the index" in capsys.readouterr().out


def test_tag_list_empty(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "tag", "ls"])
    assert "no tags yet" in capsys.readouterr().out


def test_trash_and_restore(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    target = tree / "notes.txt"
    main(["--color", "never", "trash", str(target)])
    assert "would be trashed" in capsys.readouterr().out
    assert target.exists()

    main(["--color", "never", "trash", str(target), "--apply"])
    assert "trashed 1 file" in capsys.readouterr().out
    assert not target.exists()

    main(["--color", "never", "restore", "--list"])
    assert "notes.txt" in capsys.readouterr().out

    main(["--color", "never", "restore", "--last", "1", "--apply"])
    assert "restored" in capsys.readouterr().out
    assert target.exists()


def test_trash_requires_a_path(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--color", "never", "trash"])
    assert info.value.code == 2


def test_restore_empty(tmp_path, capsys) -> None:
    main(["--color", "never", "scan", str(tmp_path)])
    capsys.readouterr()
    main(["--color", "never", "restore", "--list"])
    assert "trash is empty" in capsys.readouterr().out


def test_undo_after_organize(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    into = tree.parent / "sorted"
    main(["--color", "never", "organize", str(tree), "--into", str(into), "--apply"])
    capsys.readouterr()
    main(["--color", "never", "undo", "-n", "8"])
    assert "would be reversed" in capsys.readouterr().out
    main(["--color", "never", "undo", "-n", "8", "--apply"])
    assert "reversed" in capsys.readouterr().out
    assert (tree / "photos" / "one.jpg").exists()


def test_undo_without_journal(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "undo"])
    assert "nothing to undo" in capsys.readouterr().out


def test_stats(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--color", "never", "stats"])
    out = capsys.readouterr().out
    assert "8 files" in out
    assert "KIND" in out
    assert "YEAR" in out


def test_stats_empty(capsys, tmp_path: Path) -> None:
    main(["--color", "never", "scan", str(tmp_path)])
    capsys.readouterr()
    main(["--color", "never", "stats"])
    assert "the index is empty" in capsys.readouterr().out


def test_stats_json(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--json", "stats"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 8
    assert payload["kinds"]


def test_doctor_healthy(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    assert main(["--color", "never", "doctor"]) == 0
    assert "healthy" in capsys.readouterr().out


def test_doctor_without_index(capsys) -> None:
    assert main(["--color", "never", "doctor"]) == 1
    assert "no index at" in capsys.readouterr().out


def test_doctor_reports_missing_files(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    (tree / "notes.txt").unlink()
    db = __import__("filekeep.db", fromlist=["Database"]).Database()
    db.set_missing([str(tree / "notes.txt")])
    db.close()
    assert main(["--color", "never", "doctor", "--strict"]) == 1
    assert "deleted on disk" in capsys.readouterr().out


def test_doctor_json(tree: Path, capsys) -> None:
    scan_tree(tree, capsys)
    main(["--json", "doctor"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["index"]
    assert isinstance(payload["checks"], list)


def test_color_always_emits_ansi(tree: Path, capsys) -> None:
    main(["--color", "always", "ls"])
    capsys.readouterr()
    main(["--color", "always", "scan", str(tree)])
    assert "\x1b[" in capsys.readouterr().out


def test_parser_has_every_documented_command() -> None:
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, __import__("argparse")._SubParsersAction)
    )
    assert set(subparsers.choices) == {
        "scan",
        "ls",
        "find",
        "dupes",
        "big",
        "usage",
        "stale",
        "organize",
        "rename",
        "tag",
        "trash",
        "restore",
        "undo",
        "stats",
        "doctor",
    }


def test_bad_value_exits_with_code_two(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--color", "rainbow", "ls"])
    assert info.value.code == 2
