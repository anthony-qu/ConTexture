"""Read a run's `dialog_log.txt` into a list of sections for the web page.

The agent writes every section as `[TAG]` or `[TAG] @Agent` on a line of its own, then the
content, then one blank line (`tools._append_dialog`). A header is therefore recognised only
when it is the WHOLE line and the line before it is blank (or it is the first line). The second
condition matters: a state report contains lines such as `[STATE] turn 9`, and a budget notice
starts with `[BUDGET] 10 execution step(s) remain`; both sit inside a section, never after a
blank line, and neither is a whole-line header.
"""
from __future__ import annotations

import re
from pathlib import Path

_HEADER = re.compile(r"^\[([A-Z][A-Z0-9_-]*)\](?: @(\S+))?$")


def parse(text: str) -> list[dict]:
    """Split transcript text into sections of {kind, agent, text}."""
    sections: list[dict] = []
    current: dict | None = None
    body: list[str] = []
    prev_blank = True
    for line in text.split("\n"):
        m = _HEADER.match(line) if prev_blank else None
        if m:
            if current is not None:
                current["text"] = "\n".join(body).strip("\n")
                sections.append(current)
            current = {"kind": m.group(1), "agent": m.group(2)}
            body = []
        elif current is not None:
            body.append(line)
        prev_blank = line.strip() == ""
    if current is not None:
        current["text"] = "\n".join(body).strip("\n")
        sections.append(current)
    return sections


def read(path: Path) -> list[dict]:
    """Parse the file, leaving out a final section that may still be half written.

    `_append_dialog` writes one section per call and ends it with a blank line, so a file
    that does not end in a blank line is being written at this moment. Its last section is
    held back until the next read rather than shown cut short.
    """
    try:
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        return []
    sections = parse(text)
    if sections and not text.endswith("\n\n"):
        sections.pop()
    return sections
