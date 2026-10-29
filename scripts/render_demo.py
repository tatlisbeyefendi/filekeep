#!/usr/bin/env python3
"""Rebuild the README screenshots from real filekeep output.

    python scripts/render_demo.py

Creates a throw-away disk (scripts/make_demo_files.py), indexes it, then renders
``docs/demo.svg`` and ``docs/demo-dupes.svg``. Nothing in the images is written
by hand, so they cannot drift away from the tool.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def main() -> int:
    home = Path(tempfile.gettempdir()) / "filekeep-demo"
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), COLUMNS="112", HOME=str(home))
    env["FILEKEEP_HOME"] = str(home / ".filekeep")

    subprocess.run(
        [PYTHON, str(REPO / "scripts" / "make_demo_files.py"), str(home), "--force"],
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        [PYTHON, "-m", "filekeep", "scan", str(home), "--hash", "always"],
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        [
            PYTHON,
            "-m",
            "filekeep",
            "tag",
            "add",
            str(home / "Documents" / "contract-final.pdf"),
            "sign",
            "2026",
        ],
        check=True,
        env=env,
        capture_output=True,
    )

    shots = [
        (
            "docs/demo.svg",
            "filekeep — every file at a glance",
            "filekeep ls ~ -v --sort size",
            [
                PYTHON,
                "-m",
                "filekeep",
                "--color",
                "always",
                "ls",
                str(home),
                "-v",
                "--sort",
                "size",
                "-l",
                "12",
            ],
        ),
        (
            "docs/demo-dupes.svg",
            "filekeep dupes — identical files, one keep and the rest gone",
            "filekeep dupes ~",
            [PYTHON, "-m", "filekeep", "--color", "always", "dupes", str(home)],
        ),
    ]
    for output, title, prompt, command in shots:
        subprocess.run(
            [
                PYTHON,
                str(REPO / "scripts" / "render_demo_svg.py"),
                str(REPO / output),
                "--title",
                title,
                "--prompt",
                prompt,
                "--",
                *command,
            ],
            check=True,
            env=env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
