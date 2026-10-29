## What changed

<!-- One paragraph: the problem, then the solution. -->

## Why

<!-- The situation that made this necessary. Link an issue if there is one. -->

## How it was tested

<!-- Commands you ran, tests you added. -->

```console
$ make test
```

## Checklist

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] Changes that touch the filesystem are a dry run unless `--apply` is given
- [ ] New behaviour has a journal entry so `filekeep undo` can reverse it
- [ ] `README.md` documents any new flag, and `CHANGELOG.md` has an `[Unreleased]` entry
