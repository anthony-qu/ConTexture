"""Run one analysis for the web page, then record how it ended.

`serve.py` starts this module as a new process group whose working directory is the run's own
folder, so a figure the agent saves under a bare file name lands in the run folder rather than
anywhere else. This module starts the agent with the settings in `run.json`, waits, and
writes `exit.json`. That record is what lets the page report a finished run correctly even if
the page server was restarted while the analysis was going.

The page's Stop button sends an interrupt to the whole process group. This process ignores the
interrupt and keeps waiting, so the agent can finish its clean-up (it writes `usage.json` on
the way out) and the exit code is still recorded. If the agent does not stop in time, the
server force-stops the group, and then `stop.json` alone tells the page what happened.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path


def main(run_dir: str) -> int:
    run = Path(run_dir)
    cfg = json.loads((run / "run.json").read_text())
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    cmd = [sys.executable, "-m", "contexture.agent", cfg["data_path"], cfg["goal"],
           "--output-dir", str(run),
           "--model", cfg["model"],
           "--max-turns", str(cfg["max_turns"])]
    if cfg.get("discovery"):
        cmd.append("--discovery")
        if cfg.get("evolve"):
            cmd.append("--evolve")
        if cfg.get("discovery_model"):
            cmd += ["--discovery-model", cfg["discovery_model"]]
    # The child must receive the interrupt this process ignores, so restore the default.
    proc = subprocess.Popen(cmd, cwd=run,
                            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    returncode = proc.wait()
    if cfg.get("discovery"):
        # The agent cannot delete the environment copy it ran in, and a hard stop would leave
        # the input read-only; both are put right here, from outside the run.
        from .. import discoveryenv
        discoveryenv.cleanup(str(run))
    (run / "exit.json").write_text(json.dumps(
        {"returncode": returncode, "ended": time.time()}, indent=2))
    return returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
