"""A native "choose a file" window, opened by the server on the computer it runs on.

A web page may not learn the full path of a file picked in the browser's own dialog, so the
page asks the server instead. The server runs on the same computer as the browser in the
normal case, so the window opens there and the chosen path goes back to the page; the agent
then reads the file where it is, nothing is copied. Over a remote connection without a
screen there is no window to open, and `available()` says so.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_lock = threading.Lock()     # one window at a time
_TIMEOUT = 900               # seconds a window may stay open

PROMPT = {"file": "Choose the data file", "folder": "Choose the data folder"}


def available() -> bool:
    """Can this process open a window on a screen?"""
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None and not os.environ.get("SSH_CONNECTION")
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def pick(kind: str = "file", start: str | None = None) -> str | None:
    """Open the window and return the chosen path, or None when the user cancels."""
    if kind not in PROMPT:
        raise ValueError(f"unknown kind {kind!r}")
    start_dir = _start_dir(start)
    with _lock:
        if sys.platform == "darwin":
            return _osascript(kind, start_dir)
        if sys.platform.startswith("linux"):
            if shutil.which("zenity"):
                return _zenity(kind, start_dir)
            if shutil.which("kdialog"):
                return _kdialog(kind, start_dir)
        return _tk(kind, start_dir)


def _start_dir(start: str | None) -> str | None:
    """The folder the window opens in: the current field's folder when it exists."""
    if not start:
        return None
    p = Path(os.path.expanduser(start.strip()))
    if p.is_dir():
        return str(p)
    if p.parent.is_dir():
        return str(p.parent)
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)


def _osascript(kind: str, start_dir: str | None) -> str | None:
    what = "folder" if kind == "folder" else "file"
    where = f' default location (POSIX file "{_q(start_dir)}")' if start_dir else ""
    # System Events brings the window to the front; otherwise it can open behind the browser.
    script = (
        'tell application "System Events"\n'
        "  activate\n"
        f'  set p to POSIX path of (choose {what} with prompt "{PROMPT[kind]}"{where})\n'
        "end tell\n"
        "return p"
    )
    r = _run(["osascript", "-e", script])
    if r.returncode != 0:
        if "-128" in r.stderr or "canceled" in r.stderr.lower():
            return None
        raise RuntimeError(r.stderr.strip() or "the file window could not be opened")
    return r.stdout.strip().rstrip("/") or None


def _zenity(kind: str, start_dir: str | None) -> str | None:
    cmd = ["zenity", "--file-selection", f"--title={PROMPT[kind]}"]
    if kind == "folder":
        cmd.append("--directory")
    if start_dir:
        cmd.append(f"--filename={start_dir.rstrip('/')}/")
    r = _run(cmd)
    if r.returncode == 1:
        return None
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "the file window could not be opened")
    return r.stdout.strip() or None


def _kdialog(kind: str, start_dir: str | None) -> str | None:
    flag = "--getexistingdirectory" if kind == "folder" else "--getopenfilename"
    r = _run(["kdialog", "--title", PROMPT[kind], flag, start_dir or os.path.expanduser("~")])
    if r.returncode == 1:
        return None
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "the file window could not be opened")
    return r.stdout.strip() or None


_TK = r"""
import sys, tkinter as tk
from tkinter import filedialog
kind, start, title = sys.argv[1], sys.argv[2] or None, sys.argv[3]
root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True); root.update()
if kind == "folder":
    p = filedialog.askdirectory(title=title, initialdir=start, mustexist=True)
else:
    p = filedialog.askopenfilename(title=title, initialdir=start)
print(p or "")
"""


def _tk(kind: str, start_dir: str | None) -> str | None:
    # Windows and a Linux desktop without zenity or kdialog: Python's own window toolkit,
    # in a fresh process because it must own that process's main thread.
    r = _run([sys.executable, "-I", "-c", _TK, kind, start_dir or "", PROMPT[kind]])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip()
                           else "the file window could not be opened")
    return r.stdout.strip() or None


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
