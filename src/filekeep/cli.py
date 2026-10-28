"""Command line interface for filekeep."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from filekeep import __version__
from filekeep.db import Database, default_db_path
from filekeep.fsops import apply_moves, restore_paths, trash_paths, undo
from filekeep.humanize import (
    ago,
    human_age,
    human_size,
    parse_duration,
    parse_size,
    percent,
    plural,
)
from filekeep.index import scan
from filekeep.journal import Journal
from filekeep.kinds import known_kinds
from filekeep.plans import (
    ORGANIZE_MODES,
    RENAME_TOKENS,
    plan_duplicates,
    plan_organize,
    plan_rename,
)
from filekeep.query import (
    SORTS,
    FileFilter,
    duplicate_groups,
    search,
    unhashed,
)
from filekeep.query import (
    stats as collect_stats,
)
from filekeep.ui import (
    Style,
    ellipsize_path,
    render_bar,
    render_table,
    shorten_home,
    supports_color,
    terminal_width,
)

PROG = "filekeep"


# --------------------------------------------------------------------------- helpers
def _style(args: argparse.Namespace) -> Style:
    return Style(supports_color(getattr(args, "color", "auto")))


def _open_db(args: argparse.Namespace, *, create: bool = True) -> Database:
    return Database(getattr(args, "db", None) or default_db_path(), create=create)


def _journal(db: Database) -> Journal:
    return Journal(db.path.parent / "journal.jsonl")


def _abs_paths(values: Sequence[str]) -> list[str]:
    return [str(Path(value).expanduser().resolve()) for value in values]


def _format_row(row: Any, db: Database, *, long: bool, now: float) -> list[str]:
    path = shorten_home(row.path)
    width = max(20, terminal_width() - 42)
    cells = [
        human_size(row.size),
        human_age(row.age(now)),
        row.kind,
        ellipsize_path(path, width),
    ]
    if long:
        tags = db.tags_for(row.id)
        cells.append(",".join(tags) if tags else "-")
    return cells


def _print_rows(db: Database, rows: list[Any], args: argparse.Namespace, style: Style) -> None:
    now = time.time()
    if not rows:
        print(style.dim("no files matched"))
        return
    long = bool(getattr(args, "long", False))
    headers = ["SIZE", "AGE", "KIND", "PATH"] + (["TAGS"] if long else [])
    table = [_format_row(row, db, long=long, now=now) for row in rows]
    print(
        render_table(
            headers, table, align=["r", "r", "l", "l"] + (["l"] if long else []), style=style
        )
    )
    total = sum(row.size for row in rows)
    print(style.dim(f"\n{plural(len(rows), 'file')} · {human_size(total)}"))


def _emit_json(payload: dict[str, Any]) -> None:
    payload.setdefault("tool", PROG)
    payload.setdefault("version", __version__)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _row_json(row: Any) -> dict[str, Any]:
    return {
        "path": row.path,
        "name": row.name,
        "kind": row.kind,
        "ext": row.ext,
        "size": row.size,
        "mtime": row.mtime,
        "hash": row.hash,
        "is_link": row.is_link,
        "missing": row.missing,
    }


def _filter_from_args(args: argparse.Namespace) -> FileFilter:
    kinds = [item.rstrip(",") for item in (getattr(args, "kind", None) or [])]
    exts = [item.lower().lstrip(".") for item in (getattr(args, "ext", None) or [])]
    spec = FileFilter(
        roots=_abs_paths(getattr(args, "paths", None) or []),
        kinds=kinds,
        exts=exts,
        tags=list(getattr(args, "tag", None) or []),
        name_like=getattr(args, "name", None),
        name_glob=getattr(args, "glob", None),
        name_regex=getattr(args, "regex", None),
        path_like=getattr(args, "path_contains", None),
        include_missing=bool(getattr(args, "missing", False)),
        include_links=not bool(getattr(args, "no_links", False)),
    )
    for attribute, target in (("min_size", "min_size"), ("max_size", "max_size")):
        raw = getattr(args, attribute, None)
        if raw:
            setattr(spec, target, parse_size(raw))
    if getattr(args, "older_than", None):
        spec.older_than = parse_duration(args.older_than)
    if getattr(args, "newer_than", None):
        spec.newer_than = parse_duration(args.newer_than)
    return spec


# --------------------------------------------------------------------------- commands
def cmd_scan(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args)
    roots = _abs_paths(args.paths)
    if not roots:
        stored = db.meta_get("last_scan_roots")
        roots = [item for item in (stored or "").split(os.pathsep) if item]
    if not roots:
        print(style("nothing to scan: give a path, e.g. `filekeep scan ~/Downloads`", "red"))
        return 1
    missing_roots = [root for root in roots if not Path(root).is_dir()]
    if len(missing_roots) == len(roots):
        print(style(f"no such directory: {', '.join(missing_roots)}", "red"))
        return 1
    for root in missing_roots:
        print(style(f"skipping missing directory: {root}", "yellow"))
        roots.remove(root)

    result = scan(
        db,
        roots,
        hash_policy=args.hash,
        jobs=args.jobs,
        include_hidden=args.hidden,
        follow_symlinks=args.follow_links,
        exclude=args.exclude or (),
        prune=not args.no_prune,
        max_hash_size=parse_size(args.max_hash_size) if args.max_hash_size else 256 * 1024 * 1024,
    )
    if args.json:
        _emit_json(
            {
                "command": "scan",
                "roots": result.roots,
                "files": result.files,
                "dirs": result.dirs,
                "hashed": result.hashed,
                "unreadable": result.skipped,
                "pruned": result.pruned,
                "bytes": result.bytes,
                "elapsed_seconds": round(result.elapsed, 4),
            }
        )
        return 0
    print(
        f"{style.bold('indexed')} {plural(result.files, 'file')} in "
        f"{plural(result.dirs, 'directory', 'directories')} · {human_size(result.bytes)} · "
        f"{result.hashed} hashed · {result.pruned} pruned · {result.elapsed:.2f}s"
    )
    print(style.dim(f"index: {shorten_home(str(db.path))}"))
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    rows = search(db, spec, sort=args.sort, reverse=args.reverse, limit=args.limit)
    if args.json:
        _emit_json({"command": "ls", "count": len(rows), "files": [_row_json(row) for row in rows]})
        return 0
    if not rows and not db.count():
        print(style("the index is empty — run `filekeep scan PATH` first", "yellow"))
        return 0
    _print_rows(db, rows, args, style)
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    if args.glob:
        spec.name_glob = args.glob
    elif args.regex:
        spec.name_regex = args.regex
    else:
        spec.name_like = args.pattern
    rows = search(db, spec, sort=args.sort, limit=args.limit)
    if args.json:
        _emit_json(
            {"command": "find", "count": len(rows), "files": [_row_json(row) for row in rows]}
        )
        return 0
    if not rows:
        print(style.dim(f"no file matching {args.pattern!r}"))
        return 0
    _print_rows(db, rows, args, style)
    return 0


def cmd_dupes(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    min_size = parse_size(args.min_size) if args.min_size else 1

    if not args.no_hash:
        from filekeep.index import hash_file

        for row in unhashed(db, min_size=min_size)[: args.hash_limit]:
            digest = hash_file(row.path)
            db.update_hash(row.path, digest)

    groups = duplicate_groups(db, min_size=min_size, max_groups=args.limit, spec=spec)
    plans = plan_duplicates(groups, keep=args.keep) if groups else []
    reclaimable = sum(group[0].size * (len(group) - 1) for group in groups)

    if args.apply and groups:
        done = trash_paths(
            [plan.source for plan in plans],
            data_dir=db.path.parent,
            db=db,
            journal=_journal(db),
            dry_run=False,
        )
        if args.json:
            _emit_json(
                {
                    "command": "dupes",
                    "groups": len(groups),
                    "reclaimable": reclaimable,
                    "trashed": [{"path": source, "trashed_to": target} for source, target in done],
                }
            )
            return 0
        print(
            f"{style.bold('trashed')} {plural(len(done), 'copy', 'copies')} → "
            f"{human_size(reclaimable)} reclaimed"
        )
        print(style.dim("undo with `filekeep undo --apply`"))
        return 0

    if args.json:
        _emit_json(
            {
                "command": "dupes",
                "groups": [
                    {
                        "size": group[0].size,
                        "copies": len(group),
                        "files": [row.path for row in group],
                    }
                    for group in groups
                ],
                "reclaimable": reclaimable,
            }
        )
        return 0

    if not groups:
        print(style("no duplicates found", "green"))
        return 0

    keepers = {plan.target for plan in plans}
    for number, group in enumerate(groups, start=1):
        print(
            f"{style.bold(f'group {number}')} · {plural(len(group), 'copy', 'copies')} · "
            f"{human_size(group[0].size)} each · "
            f"{human_size(group[0].size * (len(group) - 1))} reclaimable"
        )
        ordered = sorted(group, key=lambda item: (item.path not in keepers, item.path))
        for row in ordered:
            marker = style("keep ", "green") if row.path in keepers else style("trash", "red")
            print(f"  {marker} {shorten_home(row.path)}")
        print()
    print(
        f"{plural(len(groups), 'group')} · {human_size(reclaimable)} reclaimable · "
        + style.dim("apply with `filekeep dupes --apply`")
    )
    return 0


def cmd_big(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    if args.min_size:
        spec.min_size = parse_size(args.min_size)
    rows = search(db, spec, sort="size", limit=args.limit)
    if args.json:
        _emit_json(
            {
                "command": "big",
                "count": len(rows),
                "bytes": sum(row.size for row in rows),
                "files": [_row_json(row) for row in rows],
            }
        )
        return 0
    if not rows:
        print(style.dim("nothing indexed for that filter"))
        return 0
    _print_rows(db, rows, args, style)
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    root = str(Path(args.path).expanduser().resolve()) if args.path else None
    clause, params = "missing = 0", []
    if root:
        clause += " AND path LIKE ?"
        params.append(f"{root.rstrip('/')}/%")
    rows = list(db.conn.execute(f"SELECT path, size FROM files WHERE {clause}", params))
    depth = root.rstrip("/").count("/") + max(1, args.depth) if args.path else args.depth
    buckets: dict[str, list[int]] = {}
    for row in rows:
        parts = row["path"].split("/")
        prefix = "/".join(parts[: max(1, min(depth, len(parts) - 1))]) or "/"
        bucket = buckets.setdefault(prefix, [0, 0])
        bucket[0] += row["size"]
        bucket[1] += 1
    ordered = sorted(buckets.items(), key=lambda item: item[1][0], reverse=True)[: args.limit]
    if args.json:
        _emit_json(
            {
                "command": "usage",
                "root": root,
                "depth": args.depth,
                "directories": [
                    {"path": path, "bytes": value[0], "files": value[1]} for path, value in ordered
                ],
            }
        )
        return 0
    if not ordered:
        print(style.dim("nothing indexed for that path"))
        return 0
    largest = ordered[0][1][0]
    table = []
    for path, (size, files) in ordered:
        width = max(10, terminal_width() - 46)
        table.append(
            [
                human_size(size),
                str(files),
                render_bar(size, largest, width=min(18, width // 2)),
                ellipsize_path(shorten_home(path), width),
            ]
        )
    print(
        render_table(
            ["SIZE", "FILES", "USAGE", "DIRECTORY"], table, align=["r", "r", "l", "l"], style=style
        )
    )
    print(
        style.dim(f"\n{plural(len(rows), 'file')} · {human_size(sum(row['size'] for row in rows))}")
    )
    return 0


def cmd_stale(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    spec.older_than = parse_duration(args.older_than)
    rows = search(db, spec, sort="age", limit=args.limit)
    if args.json:
        _emit_json(
            {
                "command": "stale",
                "older_than_seconds": spec.older_than,
                "count": len(rows),
                "files": [_row_json(row) for row in rows],
            }
        )
        return 0
    if not rows:
        print(style("nothing that old in the index", "green"))
        return 0
    _print_rows(db, rows, args, style)
    return 0


def cmd_organize(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    rows = search(db, spec)
    into = Path(args.into).expanduser().resolve()
    plans = plan_organize(rows, by=args.by, into=into, copy=args.copy)
    if args.json:
        _emit_json(
            {
                "command": "organize",
                "by": args.by,
                "into": str(into),
                "applied": bool(args.apply),
                "moves": [{"from": plan.source, "to": plan.target} for plan in plans],
            }
        )
        return 0
    if not plans:
        print(style.dim("nothing to move — the files are already in place"))
        return 0
    for plan in plans:
        arrow = style("→", "cyan")
        print(f"  {shorten_home(plan.source)} {arrow} {shorten_home(plan.target)}")
    verb = "copied" if args.copy else "moved"
    if args.apply:
        done = apply_moves(
            plans,
            db=db,
            journal=_journal(db),
            copy=args.copy,
            dry_run=False,
            op="organize",
        )
        print(f"\n{style.bold(verb)} {plural(len(done), 'file')} → {shorten_home(str(into))}")
        print(style.dim("undo with `filekeep undo --apply`"))
    else:
        print(
            f"\n{plural(len(plans), 'file')} would be {verb} · "
            + style.dim("dry run — add --apply to do it")
        )
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    spec = _filter_from_args(args)
    rows = search(db, spec)
    try:
        plans = plan_rename(
            rows,
            args.pattern,
            find=args.find,
            replace=args.replace,
            keep_ext=not args.no_keep_ext,
            start=args.start,
            pad=args.pad,
            dry_run=not args.apply,
        )
    except ValueError as error:
        print(style(str(error), "red"))
        return 1
    if args.json:
        _emit_json(
            {
                "command": "rename",
                "applied": bool(args.apply),
                "renames": [{"from": plan.source, "to": plan.target} for plan in plans],
            }
        )
        return 0
    if not plans:
        print(style.dim("nothing to rename"))
        return 0
    for plan in plans:
        print(f"  {Path(plan.source).name} {style('→', 'cyan')} {shorten_home(plan.target)}")
    if args.apply:
        done = apply_moves(plans, db=db, journal=_journal(db), dry_run=False, op="rename")
        print(f"\n{style.bold('renamed')} {plural(len(done), 'file')}")
        print(style.dim("undo with `filekeep undo --apply`"))
    else:
        print(
            f"\n{plural(len(plans), 'file')} would be renamed · "
            + style.dim("add --apply to do it")
        )
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    if args.action == "ls":
        tags = db.all_tags()
        if args.json:
            _emit_json(
                {"command": "tag", "tags": [{"tag": tag, "files": count} for tag, count in tags]}
            )
            return 0
        if not tags:
            print(style.dim("no tags yet — `filekeep tag add FILE tag`"))
            return 0
        print(
            render_table(
                ["FILES", "TAG"],
                [[str(count), tag] for tag, count in tags],
                align=["r", "l"],
                style=style,
            )
        )
        return 0
    path = str(Path(args.path).expanduser().resolve())
    row = db.by_path(path)
    if row is None:
        print(style(f"not in the index: {shorten_home(path)} (run `filekeep scan` first)", "red"))
        return 1
    changed = []
    for tag in args.tags:
        if args.action == "add":
            if db.add_tag(path, tag):
                changed.append(("added", tag))
            else:
                changed.append(("exists", tag))
        elif db.remove_tag(path, tag):
            changed.append(("removed", tag))
        else:
            changed.append(("absent", tag))
    if args.json:
        _emit_json(
            {"command": "tag", "path": path, "tags": db.tags_for(row.id), "changes": changed}
        )
        return 0
    for action, tag in changed:
        print(f"  {action} {tag}")
    print(style.dim(f"{shorten_home(path)} → {', '.join(db.tags_for(row.id)) or '(no tags)'}"))
    return 0


def cmd_trash(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    paths = _abs_paths(args.paths)
    if not paths:
        print(style("give at least one path", "red"))
        return 1
    done = trash_paths(
        paths, data_dir=db.path.parent, db=db, journal=_journal(db), dry_run=not args.apply
    )
    if args.json:
        _emit_json(
            {
                "command": "trash",
                "applied": bool(args.apply),
                "trashed": [{"path": source, "trashed_to": target} for source, target in done],
            }
        )
        return 0
    for source, target in done:
        print(f"  {shorten_home(source)} {style('→', 'cyan')} {shorten_home(target)}")
    if args.apply:
        print(
            f"\n{style.bold('trashed')} {plural(len(done), 'file')} · "
            + style.dim("`filekeep restore` brings it back")
        )
    else:
        print(
            f"\n{plural(len(done), 'file')} would be trashed · " + style.dim("add --apply to do it")
        )
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    entries = db.trash_entries()
    if args.ids:
        wanted = {int(value) for value in args.ids}
        entries = [entry for entry in entries if int(entry["id"]) in wanted]
    elif args.last:
        entries = entries[: args.last]
    if not entries:
        if args.json:
            _emit_json({"command": "restore", "restored": []})
            return 0
        print(style.dim("the trash is empty"))
        return 0
    if args.list and not args.apply:
        rows = [
            [
                str(entry["id"]),
                human_size(int(entry["size"])),
                human_age(time.time() - float(entry["deleted_at"])),
                ellipsize_path(
                    shorten_home(entry["original_path"]), max(20, terminal_width() - 30)
                ),
            ]
            for entry in entries
        ]
        if args.json:
            _emit_json(
                {
                    "command": "restore",
                    "entries": [
                        {
                            "id": int(entry["id"]),
                            "original_path": entry["original_path"],
                            "size": int(entry["size"]),
                            "deleted_at": float(entry["deleted_at"]),
                        }
                        for entry in entries
                    ],
                }
            )
            return 0
        print(
            render_table(
                ["ID", "SIZE", "WHEN", "ORIGINAL PATH"],
                rows,
                align=["r", "r", "r", "l"],
                style=style,
            )
        )
        print(style.dim("\nrestore with `filekeep restore --last N --apply`"))
        return 0
    done = restore_paths(entries, db=db, journal=_journal(db), dry_run=not args.apply)
    if args.json:
        _emit_json(
            {
                "command": "restore",
                "applied": bool(args.apply),
                "restored": [{"from": source, "to": target} for source, target in done],
            }
        )
        return 0
    for source, target in done:
        print(f"  {shorten_home(source)} {style('→', 'cyan')} {shorten_home(target)}")
    verb = "restored" if args.apply else "would be restored"
    print(f"\n{plural(len(done), 'file')} {verb}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    journal = _journal(db)
    if journal.is_empty():
        print(style.dim("nothing to undo"))
        return 0
    plans = undo(
        journal=journal,
        db=db,
        data_dir=db.path.parent,
        steps=args.steps,
        dry_run=not args.apply,
    )
    if args.json:
        _emit_json(
            {
                "command": "undo",
                "applied": bool(args.apply),
                "reversed": [
                    {"op": op, "from": source, "to": target} for op, source, target in plans
                ],
            }
        )
        return 0
    if not plans:
        print(style.dim("the last operations have already been reversed"))
        return 0
    for op, source, target in plans:
        arrow = style("→", "cyan")
        print(f"  {style(op, 'yellow')} {shorten_home(source)} {arrow} {shorten_home(target)}")
    verb = "reversed" if args.apply else "would be reversed"
    print(
        f"\n{plural(len(plans), 'operation')} {verb} · "
        + style.dim(f"journal: {shorten_home(str(journal.path))}")
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    result = collect_stats(db)
    if args.json:
        _emit_json(
            {
                "command": "stats",
                "files": result.files,
                "bytes": result.size,
                "missing": result.missing,
                "kinds": [
                    {"kind": item.kind, "files": item.files, "bytes": item.size}
                    for item in result.kinds
                ],
                "years": {
                    year: {"files": value[0], "bytes": value[1]}
                    for year, value in result.years.items()
                },
                "oldest": _row_json(result.oldest) if result.oldest else None,
                "newest": _row_json(result.newest) if result.newest else None,
            }
        )
        return 0
    if not result.files:
        print(style("the index is empty — run `filekeep scan PATH` first", "yellow"))
        return 0
    print(
        f"{style.bold(plural(result.files, 'file'))} · {style.bold(human_size(result.size))} · "
        f"{plural(len(result.kinds), 'kind')} · {plural(len(result.years), 'year')}"
    )
    largest = max((item.size for item in result.kinds), default=1)
    rows = [
        [
            item.kind,
            str(item.files),
            human_size(item.size),
            f"{percent(item.size, result.size):4.1f}%",
            render_bar(item.size, largest, width=16),
        ]
        for item in result.kinds
    ]
    print()
    print(
        render_table(
            ["KIND", "FILES", "SIZE", "% OF ALL", ""],
            rows,
            align=["l", "r", "r", "r", "l"],
            style=style,
        )
    )
    if result.years:
        print()
        year_rows = [
            [year, str(files), human_size(size)]
            for year, (files, size) in sorted(result.years.items())
        ]
        print(
            render_table(["YEAR", "FILES", "SIZE"], year_rows, align=["l", "r", "r"], style=style)
        )
    if result.oldest and result.newest:
        now = time.time()
        print()
        print(
            style.dim(f"oldest: {shorten_home(result.oldest.path)} ({ago(result.oldest.age(now))})")
        )
        print(
            style.dim(f"newest: {shorten_home(result.newest.path)} ({ago(result.newest.age(now))})")
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    style = _style(args)
    db = _open_db(args, create=False)
    now = time.time()
    issues: list[str] = []
    notes: list[dict[str, Any]] = []

    def note(name: str, value: Any, status: str = "ok") -> None:
        notes.append({"check": name, "value": value, "status": status})
        if status != "ok":
            issues.append(name)

    path_exists = db.path.exists()
    note("index file", shorten_home(str(db.path)), "ok" if path_exists else "missing")
    if not path_exists:
        if args.json:
            _emit_json({"command": "doctor", "checks": notes, "issues": issues})
        else:
            print(
                style(f"no index at {shorten_home(str(db.path))} — run `filekeep scan PATH`", "red")
            )
        return 1

    indexed = db.count()
    note("indexed files", indexed, "ok" if indexed else "empty")

    last_scan = db.meta_get("last_scan")
    if last_scan:
        age = now - float(last_scan)
        note("last scan", ago(age), "ok" if age < 7 * 86400 else "stale")
    else:  # pragma: no cover - practically unreachable
        note("last scan", "never", "stale")

    missing_rows = [row for row in search(db, FileFilter(include_missing=True)) if row.missing]
    gone = [row for row in missing_rows if not Path(row.path).exists()]
    note("deleted on disk", len(gone), "ok" if not gone else "attention")

    broken_links = [row for row in search(db) if row.is_link and not Path(row.path).exists()]
    note("broken symlinks", len(broken_links), "ok" if not broken_links else "attention")

    no_hash = len(unhashed(db, min_size=0))
    note("files without a hash", no_hash, "ok" if not no_hash else "attention")

    entries = db.trash_entries()
    trash_size = sum(int(entry["size"]) for entry in entries)
    note("trash", f"{plural(len(entries), 'entry', 'entries')} · {human_size(trash_size)}")

    journal = _journal(db)
    note("journal", plural(journal.count(), "operation"))

    if args.json:
        _emit_json(
            {
                "command": "doctor",
                "index": str(db.path),
                "checks": notes,
                "issues": issues,
            }
        )
    else:
        for item in notes:
            colour = {"ok": "green", "empty": "yellow", "stale": "yellow"}.get(
                item["status"], "red"
            )
            print(f"  {style(item['status'].ljust(9), colour)} {item['check']:<20} {item['value']}")
        print()
        if issues:
            print(style(f"{plural(len(issues), 'issue')} found: {', '.join(issues)}", "yellow"))
        else:
            print(style("the index looks healthy", "green"))
    return 1 if issues and args.strict else 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    """Build the full argparse tree (also used by the docs tests)."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        default=argparse.SUPPRESS,
        help="index file (default: ~/.local/share/filekeep/index.db)",
    )
    common.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default=argparse.SUPPRESS,
        help="colourise output (default: auto)",
    )
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output"
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Index, search, dedupe, sort and safely delete the files on your disk.",
        epilog="Every command that changes something is a dry run until you pass --apply.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--db", default=None, help=f"index file (default: {default_db_path()})")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    scan_parser = sub.add_parser("scan", parents=[common], help="index one or more directories")
    scan_parser.add_argument("paths", nargs="*", metavar="PATH")
    scan_parser.add_argument("--hash", choices=("auto", "always", "never"), default="auto")
    scan_parser.add_argument("--max-hash-size", default=None, metavar="SIZE")
    scan_parser.add_argument("-j", "--jobs", type=int, default=8, metavar="N")
    scan_parser.add_argument("-H", "--hidden", action="store_true", help="include dot files")
    scan_parser.add_argument("-L", "--follow-links", action="store_true")
    scan_parser.add_argument("--exclude", action="append", metavar="NAME")
    scan_parser.add_argument("--no-prune", action="store_true")
    scan_parser.set_defaults(func=cmd_scan)

    def add_filters(target: argparse.ArgumentParser) -> None:
        target.add_argument("paths", nargs="*", metavar="PATH")
        target.add_argument("--kind", action="append", choices=sorted(known_kinds()))
        target.add_argument("--ext", action="append", metavar="EXT")
        target.add_argument("--tag", action="append", metavar="TAG")
        target.add_argument("--name", metavar="TEXT", help="substring of the file name")
        target.add_argument("--glob", metavar="PATTERN")
        target.add_argument("--regex", metavar="PATTERN")
        target.add_argument("--path-contains", metavar="TEXT", dest="path_contains")
        target.add_argument("--min-size", metavar="SIZE")
        target.add_argument("--max-size", metavar="SIZE")
        target.add_argument("--older-than", metavar="AGE")
        target.add_argument("--newer-than", metavar="AGE")
        target.add_argument("--missing", action="store_true", help="include files that vanished")
        target.add_argument("--no-links", action="store_true", help="skip symlinks")
        target.add_argument("-v", "--long", action="store_true", help="show tags")

    ls_parser = sub.add_parser("ls", parents=[common], help="list indexed files")
    add_filters(ls_parser)
    ls_parser.add_argument("--sort", choices=SORTS, default="path")
    ls_parser.add_argument("-r", "--reverse", action="store_true")
    ls_parser.add_argument("-l", "--limit", type=int, default=None, metavar="N")
    ls_parser.set_defaults(func=cmd_ls)

    find_parser = sub.add_parser("find", parents=[common], help="search by name")
    find_parser.add_argument("pattern", metavar="PATTERN")
    add_filters(find_parser)
    find_parser.add_argument("--sort", choices=SORTS, default="size")
    find_parser.add_argument("-l", "--limit", type=int, default=None, metavar="N")
    find_parser.set_defaults(func=cmd_find)

    dupes_parser = sub.add_parser("dupes", parents=[common], help="find identical files by hash")
    add_filters(dupes_parser)
    dupes_parser.add_argument(
        "--keep", choices=("newest", "oldest", "first", "shortest-path"), default="newest"
    )
    dupes_parser.add_argument("-l", "--limit", type=int, default=None, metavar="N")
    dupes_parser.add_argument(
        "--no-hash", action="store_true", help="do not hash missing candidates"
    )
    dupes_parser.add_argument("--hash-limit", type=int, default=2000, metavar="N")
    dupes_parser.add_argument("--apply", action="store_true", help="trash every extra copy")
    dupes_parser.set_defaults(func=cmd_dupes)

    big_parser = sub.add_parser("big", parents=[common], help="the largest files")
    add_filters(big_parser)
    big_parser.add_argument("-l", "--limit", type=int, default=20, metavar="N")
    big_parser.set_defaults(func=cmd_big)

    usage_parser = sub.add_parser("usage", parents=[common], help="disk usage per directory")
    usage_parser.add_argument("path", nargs="?", metavar="PATH")
    usage_parser.add_argument("--depth", type=int, default=3)
    usage_parser.add_argument("-l", "--limit", type=int, default=15, metavar="N")
    usage_parser.set_defaults(func=cmd_usage)

    stale_parser = sub.add_parser("stale", parents=[common], help="files untouched for a long time")
    add_filters(stale_parser)
    stale_parser.set_defaults(older_than="1y")
    stale_parser.add_argument("-l", "--limit", type=int, default=25, metavar="N")
    stale_parser.set_defaults(func=cmd_stale)

    organize_parser = sub.add_parser("organize", parents=[common], help="sort files into folders")
    add_filters(organize_parser)
    organize_parser.add_argument("--by", choices=ORGANIZE_MODES, default="kind")
    organize_parser.add_argument("--into", required=True, metavar="DIR")
    organize_parser.add_argument("--copy", action="store_true", help="copy instead of move")
    organize_parser.add_argument("--apply", action="store_true")
    organize_parser.set_defaults(func=cmd_organize)

    rename_parser = sub.add_parser("rename", parents=[common], help="rename files from a pattern")
    add_filters(rename_parser)
    rename_parser.add_argument(
        "--pattern",
        required=True,
        metavar="PATTERN",
        help="tokens: " + ", ".join("{" + token + "}" for token in RENAME_TOKENS),
    )
    rename_parser.add_argument("--find", metavar="REGEX")
    rename_parser.add_argument("--replace", default="", metavar="TEXT")
    rename_parser.add_argument("--no-keep-ext", action="store_true")
    rename_parser.add_argument("--start", type=int, default=1)
    rename_parser.add_argument("--pad", type=int, default=0, metavar="N")
    rename_parser.add_argument("--apply", action="store_true")
    rename_parser.set_defaults(func=cmd_rename)

    tag_parser = sub.add_parser("tag", parents=[common], help="tag files and list tags")
    tag_sub = tag_parser.add_subparsers(dest="action", metavar="{add,rm,ls}")
    tag_parser.set_defaults(func=cmd_tag, action="ls")
    for action, help_text in (("add", "attach tags"), ("rm", "detach tags")):
        child = tag_sub.add_parser(action, help=help_text)
        child.add_argument("path", metavar="FILE")
        child.add_argument("tags", nargs="+", metavar="TAG")
        child.set_defaults(func=cmd_tag, action=action)
    tag_sub.add_parser("ls", help="list every tag")

    trash_parser = sub.add_parser("trash", parents=[common], help="move files to filekeep's trash")
    trash_parser.add_argument("paths", nargs="+", metavar="PATH")
    trash_parser.add_argument("--apply", action="store_true")
    trash_parser.set_defaults(func=cmd_trash)

    restore_parser = sub.add_parser("restore", parents=[common], help="bring trashed files back")
    restore_parser.add_argument("ids", nargs="*", metavar="ID")
    restore_parser.add_argument("--last", type=int, default=0, metavar="N")
    restore_parser.add_argument("--list", action="store_true")
    restore_parser.add_argument("--apply", action="store_true")
    restore_parser.set_defaults(func=cmd_restore)

    undo_parser = sub.add_parser("undo", parents=[common], help="reverse the last operations")
    undo_parser.add_argument("-n", "--steps", type=int, default=1, metavar="N")
    undo_parser.add_argument("--apply", action="store_true")
    undo_parser.set_defaults(func=cmd_undo)

    stats_parser = sub.add_parser("stats", parents=[common], help="totals by kind and year")
    stats_parser.set_defaults(func=cmd_stats)

    doctor_parser = sub.add_parser("doctor", parents=[common], help="check the index for problems")
    doctor_parser.add_argument("--strict", action="store_true", help="exit 1 when issues are found")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError:
        print(f"{PROG}: no index yet — run `{PROG} scan PATH` first", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130
    except ValueError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
