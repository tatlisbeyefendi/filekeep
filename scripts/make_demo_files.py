#!/usr/bin/env python3
"""Build a throw-away directory tree that looks like a real, slightly messy disk.

    python scripts/make_demo_files.py /tmp/filekeep-demo --force

Sizes and modification times are deliberate: the demo screenshots are rendered
from this tree, so they always describe something the tool actually did.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

DAY = 86400

# (relative path, size in bytes, age in days)
FILES: list[tuple[str, int, float]] = [
    # photos, including a duplicate pair and a huge raw file
    ("Pictures/holiday-2024.jpg", 3_842_112, 210),
    ("Pictures/holiday-2024 (copy).jpg", 3_842_112, 210),
    ("Pictures/IMG_0042.JPG", 5_112_884, 21),
    ("Pictures/IMG_0043.JPG", 4_998_112, 21),
    ("Pictures/screenshot 2026-02-11.png", 812_004, 5),
    ("Pictures/scan-raw/dump_01.cr2", 28_442_112, 400),
    # downloads that never got cleaned up
    ("Downloads/ubuntu-24.04.iso", 6_112_004, 320),
    ("Downloads/setup-1.2.3.exe", 88_112_004, 540),
    ("Downloads/invoice-march.pdf", 244_112, 33),
    ("Downloads/invoice-march (1).pdf", 244_112, 33),
    ("Downloads/notes.txt", 4_112, 2),
    # a small code project
    ("Projects/filekeep/src/filekeep/cli.py", 42_112, 1),
    ("Projects/filekeep/tests/test_cli.py", 38_112, 1),
    ("Projects/filekeep/README.md", 9_112, 1),
    ("Projects/website/index.html", 14_112, 90),
    ("Projects/website/style.css", 6_112, 90),
    ("Projects/old-experiment/main.go", 22_112, 900),
    # documents and sheets
    ("Documents/2026-plan.xlsx", 88_112, 12),
    ("Documents/contract-final.pdf", 1_112_004, 260),
    ("Documents/contract-final (1).pdf", 1_112_004, 260),
    ("Documents/meeting-notes.md", 3_112, 3),
    ("Music/podcast-ep41.mp3", 8_112_004, 60),
    ("Videos/demo-recording.mov", 22_112_004, 15),
    ("archive-2023.zip", 112_112_004, 700),
]


def build(target: Path) -> int:
    now = time.time()
    payload = b"filekeep-demo"
    for relative, size, age in FILES:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.truncate(size)
            handle.write(payload)
        stamp = now - age * DAY
        os.utime(path, (stamp, stamp))
    return len(FILES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--force", action="store_true", help="delete the target first")
    args = parser.parse_args()

    target = args.target.expanduser()
    if target.exists():
        if not args.force:
            raise SystemExit(f"{target} exists (use --force to rebuild)")
        shutil.rmtree(target)
    target.mkdir(parents=True)
    created = build(target)
    print(f"built {created} files under {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
