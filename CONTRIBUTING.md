# Contributing to filekeep

Thanks for taking the time to help. This document explains the setup, the rules the code
follows and what a good pull request looks like.

## Setup

```console
$ git clone https://github.com/tatlisbeyefendi/filekeep
$ cd filekeep
$ python -m venv .venv && . .venv/bin/activate
$ python -m pip install -e '.[dev]'
$ make test
```

`make test` runs the whole suite; `make lint` runs `ruff check` and `ruff format --check`;
`make cov` writes a coverage report; `make demo` rebuilds the screenshots in `docs/`.

## Ground rules

1. **No new dependencies.** The tool ships with the standard library only. If you think a
   dependency is unavoidable, open an issue first and explain why.
2. **Nothing destructive without `--apply`.** Any command that changes the filesystem must be a
   dry run by default and must write a journal entry so `filekeep undo` can reverse it.
3. **Never overwrite.** New paths go through `filekeep.fsops.unique_path`, which produces
   `name (2).ext` instead of clobbering an existing file.
4. **Tests come with the change.** New behaviour needs a test; a bug fix needs a test that
   failed before it.
5. **Keep the CLI documented.** `tests/test_docs.py` fails if a parser flag is missing from
   `README.md`, so add the flag to the README in the same commit.

## Style

- Python 3.11 syntax, type hints on public functions, no `Any` where a real type fits.
- Line length 100, formatted with `ruff format`, linted with `ruff check --select E,F,W,I,UP,B,SIM,C4,RUF`.
- Docstrings explain *why*, not *what*; the code should be readable on its own.
- Output is English, and so are code, commit messages and documentation.

## Commit messages

Conventional commits, one idea per commit:

```
feat(dupes): keep the shortest path when two copies share an mtime
fix(cli): do not create the index when a read-only command runs
docs(readme): document --hash-limit
```

The body explains the reason for the change, not the diff.

## Pull requests

- One feature or fix per pull request; keep the diff reviewable.
- Describe the problem first, then the solution, then how you tested it.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- CI must be green: tests on every supported Python version, lint, and a wheel install smoke test.

## Reporting bugs

Open an issue with the output of `filekeep --version`, your operating system, the exact command
you ran, what you expected and what happened. If the index is involved, `filekeep doctor --json`
is usually the fastest way to show the state.
