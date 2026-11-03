"""Copy every indirect package pin from uv.lock into pyproject.toml.

`uv tool install` resolves the package's dependencies afresh and ignores uv.lock, so an
indirect package left free can drift to a version that was never tested, or, as happened on
2026-11-02 with s3fs, to one that no longer builds. This script keeps the two in step: the
block between the BEGIN/END markers in pyproject.toml lists, with its platform markers,
every package in uv.lock that the hand-written dependency list above it does not already pin.

Run it after every `uv lock`:

    python pin_from_lock.py && uv lock && git diff --stat
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"
BEGIN = "    # --- BEGIN generated from uv.lock by pin_from_lock.py; do not edit by hand ---"
END = "    # --- END generated from uv.lock ---"


def exported_requirements() -> list[str]:
    out = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--no-header",
         "--no-annotate", "--no-dev"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip() and not line.startswith("#")]


def name_of(req: str) -> str:
    return re.match(r"^([A-Za-z0-9_.\-]+)", req).group(1).lower().replace("_", "-")


def main() -> None:
    text = PYPROJECT.read_text()
    if BEGIN in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
    else:
        # First run: the block goes just before the closing bracket of `dependencies`.
        m = re.search(r"\n\]\n\n\[build-system\]", text)
        if not m:
            sys.exit("could not find the end of the dependencies list")
        head, tail = text[: m.start() + 1], text[m.start() + 1:]
    hand_written = {name_of(r) for r in re.findall(r'^\s*"([^"]+)",', head, flags=re.M)}
    lines = [f'    "{req}",' for req in exported_requirements() if name_of(req) not in hand_written]
    block = "\n".join([BEGIN, *lines, END])
    PYPROJECT.write_text(head + block + "\n" + tail)
    print(f"{len(lines)} indirect pins written; {len(hand_written)} hand-written pins kept")


if __name__ == "__main__":
    main()
