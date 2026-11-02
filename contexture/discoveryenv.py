"""What the INSTALLED package needs so that method discovery can switch environments.

`discovery.py` is the measured agent's module, unchanged apart from its imports. A method
discovery run that requests a method clones a small conda environment (`omics-discovery-min`)
and restarts the agent inside it, so that the discovered method's own version pins win over
everything in the analysis environment. The measured agent restarts itself BY FILE PATH from a
checkout that is on `sys.path`; an installed package has neither, and this module supplies the
two things it lacks:

- `build_template()` builds `omics-discovery-min` on the user's computer (the recipe of
  `analysis/discovery/make_discovery_min.sh`, with the agent framework pinned to the versions
  this package pins);
- `stage_package()` + `exec_in()` copy this package next to the run and restart the agent
  inside the clone as `python -m contexture.agent`, with only that copy on `PYTHONPATH`. The
  analysis environment's own site-packages are deliberately NOT put on the path: that would
  carry its scientific stack into the clone and defeat the reason the clone exists.

Without conda the run still works: `discovery.bootstrap()` then stays in the analysis
environment and installs the discovered method into an overlay folder beside the run, which is
fine for most methods and wrong only for a method whose pins conflict with the analysis stack.
`status()` tells the page and the terminal which of the two will happen.

Nothing here changes what the agents see: prompts, skills, tools and the discovery sequence
are the measured ones.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import discovery

PACKAGE_DIR = Path(__file__).resolve().parent          # .../contexture
TEMPLATE = discovery.DISCOVERY_BASE_ENV                 # "omics-discovery-min"
PY_VERSION = "3.11"              # published methods often have no wheel for a newer Python
# The agent process itself must import these inside the clone, and nothing scientific. The
# versions are this package's pins (pyproject.toml), so the framework is the same in both
# interpreters of one run.
FRAMEWORK = ["openai-agents==0.17.3", "openai==2.37.0", "litellm==1.85.1",
             "python-dotenv==1.2.2", "httpx", "setuptools<81"]
SCIENTIFIC = ("numpy", "scipy", "pandas", "scanpy", "anndata", "matplotlib")

_CONDA_CANDIDATES = [
    "~/miniforge3/bin/conda", "~/mambaforge/bin/conda", "~/miniconda3/bin/conda",
    "~/anaconda3/bin/conda", "~/micromamba/bin/conda",
    "/opt/homebrew/Caskroom/miniforge/base/bin/conda", "/opt/homebrew/bin/conda",
    "/opt/miniconda3/bin/conda", "/opt/conda/bin/conda", "/usr/local/bin/conda",
]


def find_conda() -> str | None:
    """Locate conda and export CONDA_EXE so `discovery._conda_binary()` finds the same one.

    `discovery` already checks CONDA_EXE, PATH and a few home folders. Users of this package
    often have Miniforge or a Homebrew install instead, so a few more places are tried here,
    and the answer is handed to `discovery` through the variable it reads first.
    """
    found = discovery._conda_binary()
    if not found:
        for cand in _CONDA_CANDIDATES:
            p = Path(os.path.expanduser(cand))
            if p.is_file() and os.access(p, os.X_OK):
                found = str(p)
                break
    if found:
        os.environ.setdefault("CONDA_EXE", found)
    return found


def template_path() -> Path | None:
    if not find_conda():
        return None
    return discovery._conda_env_path(TEMPLATE)


def status() -> dict:
    """For the page and the terminal: what a discovery run on this computer will do."""
    conda = find_conda()
    template = template_path() if conda else None
    return {
        "conda": conda,
        "template": str(template) if template else None,
        "template_name": TEMPLATE,
        "isolated": bool(template),
        "uv": bool(shutil.which("uv")),
    }


def explain(st: dict | None = None) -> str:
    """One or two plain sentences about `status()`, for the terminal and the page."""
    st = st or status()
    if st["isolated"]:
        return (f"Discovered methods are installed in a fresh copy of the conda environment "
                f"'{st['template_name']}', one copy per run, which is removed when the run ends.")
    if st["conda"]:
        return (f"conda was found but the environment '{st['template_name']}' does not exist, so "
                f"a discovered method would be installed beside the run, inside the analysis "
                f"environment's versions. Run `contexture setup-discovery` once to build it.")
    return ("conda was not found, so a discovered method would be installed beside the run, inside "
            "the analysis environment's versions. Install Miniforge "
            "(https://conda-forge.org/download/) and run `contexture setup-discovery` once for an "
            "isolated environment per run.")


def _run(cmd: list[str], log, timeout: int) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def build_template(log=print, name: str = TEMPLATE) -> Path:
    """Build the template environment. Returns its path; raises RuntimeError with the reason.

    The recipe is `analysis/discovery/make_discovery_min.sh`: Python 3.11, pip and
    setuptools<81 from conda-forge (published code still imports `pkg_resources`, removed in
    setuptools 81), then the agent framework with pip, and NOTHING scientific, so that a
    method's own install brings the numpy and scanpy it was written against.
    """
    conda = find_conda()
    if not conda:
        raise RuntimeError("conda was not found. Install Miniforge from "
                           "https://conda-forge.org/download/ (or any conda), open a new "
                           "terminal, and run `contexture setup-discovery` again.")
    existing = discovery._conda_env_path(name)
    if existing:
        log(f"the environment '{name}' already exists at {existing}; nothing to build.")
        return existing
    log(f"building the conda environment '{name}' on Python {PY_VERSION} (the agent framework "
        f"only, nothing scientific). This takes a few minutes the first time.")
    proc = _run([conda, "create", "-n", name, "-c", "conda-forge", "--override-channels", "-y",
                 "-q", f"python={PY_VERSION}", "pip", "setuptools<81"], log, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError("conda could not create the environment:\n" +
                           (proc.stdout + proc.stderr)[-1500:])
    prefix = discovery._conda_env_path(name)
    if prefix is None:
        raise RuntimeError(f"conda created '{name}' but `conda env list` does not show it.")
    pip = prefix / ("Scripts" if os.name == "nt" else "bin") / "pip"
    proc = _run([str(pip), "install", "-q", "--no-input", "--disable-pip-version-check",
                 *FRAMEWORK], log, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError("pip could not install the agent framework into the new "
                           "environment:\n" + (proc.stdout + proc.stderr)[-1500:])
    # setuptools may have moved forward as a build dependency of the above; pin it again.
    _run([str(pip), "install", "-q", "--no-input", "--disable-pip-version-check",
          "setuptools<81"], log, timeout=600)
    check_template(prefix, log)
    log(f"done: {prefix}")
    return prefix


def check_template(prefix: Path, log=print) -> None:
    """Prove the environment is what a run needs: the framework imports, nothing scientific."""
    py = prefix / ("python.exe" if os.name == "nt" else "bin/python")
    code = (
        "import importlib, json, sys\n"
        "need = ['agents', 'agents.extensions.models.litellm_provider', 'litellm', 'dotenv',"
        " 'httpx', 'pkg_resources']\n"
        "bad = [m for m in need if importlib.util.find_spec(m.split('.')[0]) is None]\n"
        "for m in need:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception as e: bad.append(f'{m}: {type(e).__name__}: {e}')\n"
        f"present = [m for m in {list(SCIENTIFIC)!r} if importlib.util.find_spec(m)]\n"
        "print(json.dumps({'bad': bad, 'present': present}))\n"
    )
    proc = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=300)
    try:
        res = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        raise RuntimeError("could not check the new environment:\n" + proc.stdout + proc.stderr)
    if res["bad"]:
        raise RuntimeError("the agent framework does not import in the new environment: "
                           + "; ".join(res["bad"]))
    if res["present"]:
        raise RuntimeError(f"the new environment carries {', '.join(res['present'])}; it must "
                           f"carry no scientific package, or a method's own pins cannot win.")
    log("checked: the agent framework imports; no scientific package is present.")


# --------------------------------------------------------------------------- the restart

def stage_package(output_dir: str) -> Path:
    """Copy this package beside the run, for the clone's PYTHONPATH. Returns the parent folder.

    A copy, not the installed location: the installed `contexture` sits in a site-packages
    folder full of the analysis stack, and putting that folder on the clone's path would carry
    numpy, scanpy and the rest into the clone. The copy is small (prompts, skills, code) and is
    the same code this process is running. The folder starts with a dot so the page's file
    list does not show it.
    """
    root = Path(output_dir) / "discovery" / ".pkg"
    dest = root / PACKAGE_DIR.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PACKAGE_DIR, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "static"))
    return root


def exec_in(env_python: str, output_dir: str, argv: list[str]) -> None:
    """Restart the agent inside `env_python` with the same arguments. Does not return.

    `discovery.bootstrap()` short-circuits on the way back in (it recognises the clone by
    `sys.prefix`), so the reporter, skill maker and planner do not run twice.
    """
    pkg_root = stage_package(output_dir)
    prev = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(pkg_root) + (os.pathsep + prev if prev else "")
    os.environ["PYTHONSAFEPATH"] = "1"        # the run's working folder stays off the path
    # os.execv does not flush Python's buffers; redirected to a file, every line printed so
    # far would be lost (measured on the first discovery run of the measured agent).
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(env_python, [env_python, "-m", "contexture.agent", *argv])


def cleanup(output_dir: str, log=print) -> None:
    """After the run: delete its environment clone and make the input writable again.

    The agent cannot delete the environment it is running in, so this is called by the
    process that started it (`webui.runner`, or `cli` after `contexture run`).
    """
    try:
        discovery.restore_input(output_dir, log=log)
    except Exception as exc:
        log(f"[DISCOVERY] could not restore the input's permissions: {exc}")
    if find_conda():
        try:
            discovery.cleanup_run_env(Path(output_dir).name, log=log)
        except Exception as exc:
            log(f"[DISCOVERY] could not remove the run environment: {exc}")
    shutil.rmtree(Path(output_dir) / "discovery" / ".pkg", ignore_errors=True)
