"""The `contexture` command."""
from __future__ import annotations

import os
import sys

from . import __version__, keys

USAGE = f"""ConTexture {__version__}: an autonomous agent for spatial multi-omics analysis.

  contexture                       start the web page and open it in your browser
  contexture serve [options]       the same, with options (see `contexture serve --help`)
  contexture run DATA "GOAL" ...   run one analysis in the terminal (see `contexture run --help`)
  contexture key                   add or change a model API key in the terminal
                                   (the web page has a "Model keys" panel too)
  contexture setup-discovery       build the conda environment that method discovery
                                   installs methods into (needs conda; run once)
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
    if command == "setup-discovery":
        from . import discoveryenv
        try:
            discoveryenv.build_template()
        except RuntimeError as exc:
            print(f"Not built: {exc}", file=sys.stderr)
            sys.exit(1)
        print(discoveryenv.explain())
        return
    if command not in ("serve", "run"):
        print(f"Unknown command {command!r}.\n\n{USAGE}", file=sys.stderr)
        sys.exit(2)

    keys.load()
    asking_for_help = any(a in ("-h", "--help") for a in rest)

    if command == "serve":
        # No terminal question here: the page opens its "Model keys" panel when no key is set.
        from . import serve
        serve.main(rest)
        return

    if not asking_for_help:
        keys.ask_and_save()

    # `run`: the agent's own command line. PYTHONSAFEPATH keeps the current folder, where the
    # agent writes files, off the import path.
    if not asking_for_help and not any(a == "--model" or a.startswith("--model=") for a in rest):
        rest += ["--model", keys.default_model()]
    os.environ["PYTHONSAFEPATH"] = "1"
    cmd = [sys.executable, "-m", "contexture.agent", *rest]
    if asking_for_help or "--discovery" not in rest:
        os.execv(sys.executable, cmd)          # the same interpreter, nothing left to do after
    # A method discovery run may restart itself inside a conda environment copy that it cannot
    # delete from within, and it makes the input read-only for its duration. Stay behind as
    # the parent to tidy both up when it ends (the page's runner does the same).
    import signal
    import subprocess
    out = next((rest[i + 1] for i, a in enumerate(rest) if a == "--output-dir" and i + 1 < len(rest)),
               next((a.split("=", 1)[1] for a in rest if a.startswith("--output-dir=")),
                    os.path.join(os.getcwd(), "contexture-output")))
    # Ctrl-C goes to the agent, which cleans up and exits; this process ignores it and waits.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    proc = subprocess.Popen(cmd, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    rc = proc.wait()
    from . import discoveryenv
    discoveryenv.cleanup(out)
    sys.exit(rc)
