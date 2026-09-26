"""The `contexture` command."""
from __future__ import annotations

import os
import sys

from . import __version__, keys

USAGE = f"""ConTexture {__version__}: an autonomous agent for spatial multi-omics analysis.

  contexture                       start the web page and open it in your browser
  contexture serve [options]       the same, with options (see `contexture serve --help`)
  contexture run DATA "GOAL" ...   run one analysis in the terminal (see `contexture run --help`)
  contexture key                   add or change a model API key
  contexture --version             print the version
"""


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return
    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        return
    # A bare `contexture`, or one that starts with an option, means `contexture serve`.
    command, rest = (argv[0], argv[1:]) if argv and not argv[0].startswith("-") else ("serve", argv)

    if command == "key":
        keys.load()
        keys.ask_and_save(always=True)
        return
    if command not in ("serve", "run"):
        print(f"Unknown command {command!r}.\n\n{USAGE}", file=sys.stderr)
        sys.exit(2)

    keys.load()
    asking_for_help = any(a in ("-h", "--help") for a in rest)
    if not asking_for_help:
        keys.ask_and_save()

    if command == "serve":
        from . import serve
        serve.main(rest)
        return

    # `run`: the agent's own command line, in this same interpreter. PYTHONSAFEPATH keeps the
    # current folder, where the agent writes files, off the import path.
    if not asking_for_help and not any(a == "--model" or a.startswith("--model=") for a in rest):
        rest += ["--model", keys.default_model()]
    os.environ["PYTHONSAFEPATH"] = "1"
    os.execv(sys.executable, [sys.executable, "-m", "contexture.agent", *rest])
