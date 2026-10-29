# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-10-30

First release.

### Added

- `scan`: incremental indexing of one or more directories into a single SQLite file, with
  parallel SHA-256 hashing, `--hash {auto,always,never}`, `--max-hash-size`, `--exclude`,
  hidden-file and symlink handling, and pruning of deleted files.
- `ls` and `find`: filtering by kind, extension, name, glob, regex, path, size, age, tag and
  symlink status, with `--sort`, `--limit`, `--reverse` and a `TAGS` column.
- `dupes`: duplicate detection grouped by size then confirmed by digest, with
  `--keep {newest,oldest,first,shortest-path}` and `--apply` to move extra copies to the trash.
- `big`, `usage`, `stale` and `stats`: where the space went and what has not been touched in a
  while.
- `organize`: rule-based moves into `Photos/`, `Archives/`, `2026-03/` and friends, with
  `--by {kind,ext,year,month,first-letter}`, `--copy` and dry-run-by-default.
- `rename`: token patterns (`{stem}`, `{ext}`, `{year}`, `{n}`, `{parent}`, …) with regex
  substitution, zero padding and collision-safe targets.
- `tag`: labels stored in the index, usable from every filter.
- `trash`, `restore` and `undo`: a real trash folder plus a JSONL journal, so every operation
  filekeep performs can be reversed.
- `doctor`: reports stale scans, rows deleted on disk, broken symlinks, files without a digest,
  trash contents and journal length.
- `--json` on every command, `--color {auto,always,never}` honouring `NO_COLOR`, and exit code 1
  for `doctor --strict` when something needs attention.
- Bilingual documentation (English and Turkish), a generated terminal demo and a CI matrix over
  Python 3.11–3.14 on Linux, macOS and Windows.

[Unreleased]: https://github.com/tatlisbeyefendi/filekeep/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tatlisbeyefendi/filekeep/releases/tag/v0.1.0
