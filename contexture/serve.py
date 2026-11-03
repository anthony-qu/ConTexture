"""A local web page for ConTexture.

    contexture [serve] [--port 8765] [--runs-dir contexture-runs] [--max-concurrent 1]

Open the address it prints (it opens by itself on a computer with a screen). The page starts analyses, shows each one as it runs, and lists
past runs.

How it is built, and why:

- EACH ANALYSIS IS ITS OWN PROCESS. The agent keeps every code cell's variables in one
  module-level namespace and captures printed output for the whole process, so two analyses
  must never share a Python process. The page starts `webui.runner` in a new process group,
  which runs `agent.py`, and then only READS the run's folder. A run therefore keeps going if
  the browser is closed or this server is restarted, and a reopened page shows everything
  written so far.
- The run's working directory is its own folder, so a figure saved under a bare file name
  lands with the run rather than in the code folder.
- THE ADDRESS CARRIES A RANDOM ACCESS CODE, as Jupyter's does. The server listens only on this
  computer's own address, but on a shared machine such as a cluster node every other user can
  reach that address too, and an open page would let them start analyses billed to your key.
- API keys: the page's "Model keys" panel saves a key to the user's own settings file (see
  `keys.py`), readable only by its owner, and the server then passes it to every new run. A
  saved key is never sent back to the browser; the page sees only where a key came from and its
  last four characters.
- Method discovery and skill evolution are not offered here yet; they need a separate conda
  environment that this repository does not build.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from markdown_it import MarkdownIt
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from starlette.concurrency import run_in_threadpool

from . import discoveryenv, keys
from .webui import filepick, transcript

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "webui"

DEFAULT_MODEL = re.search(r'^DEFAULT_MODEL = "([^"]+)"', (ROOT / "agent.py").read_text(),
                          re.M).group(1)
DEFAULT_TURNS = 30                   # agent.py's own --max-turns default
SUGGESTED_MODELS = [
    DEFAULT_MODEL,
    "anthropic/claude-opus-5",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "openai/gpt-5.6-sol",
    "gemini/gemini-2.5-pro",
]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
BOOKKEEPING = {"run.json", "exit.json", "stop.json"}
RUN_ID = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]{0,48}$")
STOP_GRACE_SECONDS = 20
OUTPUT_SHOWN = 20_000                # characters of one output block sent to the page
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_md = MarkdownIt("commonmark", {"html": False}).enable("table")
_procs: dict[str, subprocess.Popen] = {}     # runs started by THIS server, for reaping
_lock = threading.Lock()


class Settings:
    runs_dir: Path = Path.cwd() / "contexture-runs"
    max_concurrent: int = 1
    token: str = ""
    cookie: str = "contexture"


# --------------------------------------------------------------------------- runs on disk

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _alive(rid: str, pid: int | None) -> bool:
    proc = _procs.get(rid)
    if proc is not None:                       # our own child: poll() also reaps it
        return proc.poll() is None
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _usage(run: Path) -> dict:
    calls = inp = cached = out = 0
    try:
        for line in (run / "usage.jsonl").read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            calls += 1
            inp += row.get("input_tokens") or 0
            cached += row.get("cached_input_tokens") or 0
            out += row.get("output_tokens") or 0
    except FileNotFoundError:
        pass
    return {"model_calls": calls, "input_tokens": inp, "cached_input_tokens": cached,
            "output_tokens": out}


def _status(run: Path) -> dict:
    cfg = _read_json(run / "run.json") or {}
    ended = _read_json(run / "exit.json")
    stop = (run / "stop.json").exists()
    note = ""
    if ended is not None:
        rc = ended.get("returncode")
        status = "stopped" if stop else ("finished" if rc == 0 else "failed")
        end_time = ended.get("ended")
    elif _alive(run.name, cfg.get("pid")):
        status, end_time = ("stopping" if stop else "running"), None
    else:
        # Ended without writing exit.json: force-stopped, or killed from outside (for
        # example out of memory, which leaves no traceback).
        status = "stopped" if stop else "ended"
        if not stop:
            note = "The run ended without recording how. It may have run out of memory."
        log = run / "dialog_log.txt"
        end_time = (log if log.exists() else run / "run.json").stat().st_mtime
    console = run / "console.txt"
    if status == "finished" and console.exists() and \
            "max turns reached" in console.read_text(errors="replace"):
        note = "The turn budget ran out before the agent said it was done."
    return {"id": run.name, "goal": cfg.get("goal", ""), "data_path": cfg.get("data_path", ""),
            "model": cfg.get("model", ""), "max_turns": cfg.get("max_turns"),
            "discovery": bool(cfg.get("discovery")), "evolve": bool(cfg.get("evolve")),
            "discovery_model": cfg.get("discovery_model") or "",
            "created": cfg.get("created"), "ended": end_time, "status": status,
            "active": status in ("running", "stopping"), "note": note}


def _runs() -> list[Path]:
    d = Settings.runs_dir
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if RUN_ID.match(p.name) and (p / "run.json").exists()),
                  key=lambda p: p.name, reverse=True)


def _run_dir(rid: str) -> Path | None:
    if not RUN_ID.match(rid):
        return None
    run = Settings.runs_dir / rid
    return run if (run / "run.json").exists() else None


def _walk(run: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(run):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "__")))
        for name in filenames:
            if not name.startswith("."):
                found.append(Path(dirpath) / name)
        if len(found) > 2000:
            break
    return found


def _file_entry(run: Path, path: Path) -> dict:
    st = path.stat()
    return {"path": path.relative_to(run).as_posix(), "size": st.st_size, "mtime": st.st_mtime}


def _slug(goal: str) -> str:
    words = re.findall(r"[a-z0-9]+", goal.lower())
    return "-".join(words)[:40].strip("-")


# --------------------------------------------------------------------------- handlers

def _index(request: Request):
    return FileResponse(WEB / "static" / "index.html", headers={"Cache-Control": "no-cache"})


_PROVIDER_NAMES = {"OPENAI": "OpenAI", "DEEPSEEK": "DeepSeek", "ANTHROPIC": "Anthropic",
                   "GEMINI": "Gemini", "OPENROUTER": "OpenRouter", "MISTRAL": "Mistral",
                   "TOGETHERAI": "Together AI", "XAI": "xAI", "GROQ": "Groq"}


def _config(request: Request):
    providers = sorted(_PROVIDER_NAMES.get(k[: -len("_API_KEY")],
                                           k[: -len("_API_KEY")].replace("_", " ").title())
                       for k in keys.found())
    running = sum(1 for r in _runs() if _status(r)["active"])
    default = keys.default_model()       # a model the user's own key can actually call
    return JSONResponse({"default_model": default, "default_turns": DEFAULT_TURNS,
                         "models": list(dict.fromkeys([default, *SUGGESTED_MODELS])),
                         "keys": providers,
                         "runs_dir": str(Settings.runs_dir),
                         "max_concurrent": Settings.max_concurrent, "running": running,
                         "discovery": _discovery_status(),
                         "can_pick": filepick.available()})


async def _pick(request: Request):
    """Open the computer's own file window and answer with the chosen path.

    The window opens on the computer the server runs on, which is the browser's computer in
    the normal case. `path` is null when the user cancels.
    """
    if not filepick.available():
        return JSONResponse({"error": "This computer has no screen to open a file window on. "
                                      "Type or paste the path instead."}, status_code=400)
    body = await request.json()
    kind = "folder" if body.get("kind") == "folder" else "file"
    start = str(body.get("start") or "")[:4096]
    try:
        path = await run_in_threadpool(filepick.pick, kind, start)
    except Exception as exc:  # the window failed, not the user
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"path": path})


_disc_status: tuple[float, dict] = (0.0, {})


def _discovery_status() -> dict:
    """`discoveryenv.status()` plus its explanation, cached briefly: it asks conda each time."""
    global _disc_status
    if time.time() - _disc_status[0] > 30:
        st = discoveryenv.status()
        st["explain"] = discoveryenv.explain(st)
        _disc_status = (time.time(), st)
    return _disc_status[1]


def _key_file() -> str:
    """The settings file's location, with the home folder written as ~ for the page."""
    path, home = str(keys.settings_file()), str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def _keys(request: Request):
    return JSONResponse({"file": _key_file(), "keys": keys.status()})


async def _save_key(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "The request was not readable."}, status_code=400)
    var = str(body.get("var", "")).strip().upper()
    value = str(body.get("value", ""))
    if not keys.KEY_NAME.match(var):
        return JSONResponse({"error": "A key's name must end in _API_KEY, for example "
                                      "MISTRAL_API_KEY."}, status_code=400)
    if not value.strip():
        return JSONResponse({"error": "Paste the key first."}, status_code=400)
    try:
        keys.save(var, value)
    except ValueError as e:
        return JSONResponse({"error": f"Not saved: {e}."}, status_code=400)
    return JSONResponse({"file": _key_file(), "keys": keys.status()})


def _remove_key(request: Request):
    var = request.path_params["var"]
    if not keys.remove(var):
        return JSONResponse({"error": "That key is not in the settings file, so there is nothing "
                                      "to remove here."}, status_code=404)
    return JSONResponse({"file": _key_file(), "keys": keys.status()})


def _list(request: Request):
    return JSONResponse({"runs": [_status(r) for r in _runs()]})


async def _start(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "The request was not readable."}, status_code=400)
    raw_path = str(body.get("data_path", "")).strip()
    goal = str(body.get("goal", "")).strip()
    model = str(body.get("model") or keys.default_model()).strip()
    raw_turns = body.get("max_turns")
    try:
        # Only a MISSING value falls back to the default. `or` would also turn an explicit 0
        # into 30 and start a run the user asked to be impossible.
        max_turns = DEFAULT_TURNS if raw_turns in (None, "") else int(raw_turns)
    except (TypeError, ValueError):
        max_turns = 0
    if not raw_path:
        return JSONResponse({"error": "Enter the path to your data."}, status_code=400)
    data_path = Path(os.path.expanduser(raw_path)).resolve()
    if not data_path.exists():
        return JSONResponse({"error": f"Nothing exists at {data_path}. Check the path; it must "
                                      "be on the computer running this page."}, status_code=400)
    if not goal:
        return JSONResponse({"error": "Describe what you want the analysis to do."},
                            status_code=400)
    if not re.fullmatch(r"[\w./:@-]{3,120}", model):
        return JSONResponse({"error": "That model name does not look right."}, status_code=400)
    if not 1 <= max_turns <= 500:
        return JSONResponse({"error": "The turn budget must be between 1 and 500."},
                            status_code=400)
    discovery = bool(body.get("discovery"))
    evolve = bool(body.get("evolve"))
    discovery_model = str(body.get("discovery_model") or "").strip()
    if evolve and not discovery:
        return JSONResponse({"error": "Skill evolution runs inside method discovery; turn "
                                      "method discovery on as well."}, status_code=400)
    if discovery_model and not re.fullmatch(r"[\w./:@-]{3,120}", discovery_model):
        return JSONResponse({"error": "That discovery model name does not look right."},
                            status_code=400)
    with _lock:
        running = sum(1 for r in _runs() if _status(r)["active"])
        if running >= Settings.max_concurrent:
            return JSONResponse({"error": f"{running} analysis already running. This page allows "
                                          f"{Settings.max_concurrent} at a time; start the server "
                                          "with --max-concurrent to allow more."},
                                status_code=409)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rid = f"{stamp}-{_slug(goal)}"
        while (Settings.runs_dir / rid).exists():
            time.sleep(1)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            rid = f"{stamp}-{_slug(goal)}"
        run = Settings.runs_dir / rid
        run.mkdir(parents=True)
        cfg = {"goal": goal, "data_path": str(data_path), "model": model,
               "max_turns": max_turns, "created": time.time()}
        if discovery:
            cfg.update({"discovery": True, "evolve": evolve,
                        "discovery_model": discovery_model or None})
        (run / "run.json").write_text(json.dumps(cfg, indent=2))
        console = open(run / "console.txt", "w")
        proc = subprocess.Popen(
            [sys.executable, "-m", "contexture.webui.runner", str(run)],
            cwd=run, stdout=console, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONSAFEPATH": "1"})
        console.close()
        _procs[rid] = proc
        cfg["pid"] = proc.pid
        (run / "run.json").write_text(json.dumps(cfg, indent=2))
    return JSONResponse({"id": rid})


def _detail(request: Request):
    run = _run_dir(request.path_params["rid"])
    if run is None:
        return JSONResponse({"error": "No such run."}, status_code=404)
    info = _status(run)
    files = [p for p in _walk(run) if p.name not in BOOKKEEPING]
    info["usage"] = _usage(run)
    info["figures"] = [_file_entry(run, p) for p in
                       sorted((p for p in files if p.suffix.lower() in IMAGE_SUFFIXES),
                              key=lambda p: p.stat().st_mtime)]
    info["files"] = [_file_entry(run, p) for p in sorted(files)]
    if info["status"] in ("failed", "ended"):
        tail = (run / "console.txt").read_text(errors="replace")[-4000:] \
            if (run / "console.txt").exists() else ""
        info["console_tail"] = tail
    return JSONResponse(info)


def _log(request: Request):
    run = _run_dir(request.path_params["rid"])
    if run is None:
        return JSONResponse({"error": "No such run."}, status_code=404)
    try:
        since = max(0, int(request.query_params.get("since", "0")))
    except ValueError:
        since = 0
    sections = transcript.read(run / "dialog_log.txt")
    out = []
    for s in sections[since:]:
        # Some libraries colour their log lines with terminal codes, which a page shows as junk.
        text = _ANSI.sub("", s["text"])
        item = {"kind": s["kind"], "agent": s["agent"], "text": text}
        if s["kind"] == "AGENT":
            item["html"] = _md.render(text)
        elif len(text) > OUTPUT_SHOWN:
            item["text"] = text[:14_000] + "\n\n[... shortened for the page; the full text is in " \
                "dialog_log.txt ...]\n\n" + text[-5_000:]
            item["shortened"] = True
        out.append(item)
    return JSONResponse({"total": len(sections), "sections": out})


def _read_text(path: Path, limit: int = 200_000) -> str | None:
    try:
        return path.read_text(errors="replace")[:limit]
    except FileNotFoundError:
        return None


def _discovery(request: Request):
    """The documents a method discovery run writes before the analysis, rendered for the page.

    Everything comes from files in the run's `discovery/` folder, so a reopened page shows
    the same as a live one. Transcripts and token usage inside the JSON reports are not sent;
    the page has the transcript, and the reports can be downloaded from the Files tab.
    """
    run = _run_dir(request.path_params["rid"])
    if run is None:
        return JSONResponse({"error": "No such run."}, status_code=404)
    d = run / "discovery"
    out: dict = {"report": None, "skills": [], "evolution": None, "plan": None,
                 "requests": None, "method": None}
    text = _read_text(d / "data_report.md")
    if text is not None:
        out["report"] = _md.render(text)
    ev = _read_json(d / "evolution_report.json")
    if ev is not None:
        out["evolution"] = {"status": ev.get("status"), "target": ev.get("target"),
                            "error": ev.get("error"), "elapsed_sec": ev.get("elapsed_sec"),
                            "model": ev.get("maker_model"),
                            "n_snippets_passed": ev.get("n_snippets_passed")}
    if (d / "evolved").is_dir():
        for p in sorted((d / "evolved").glob("*.md")):
            out["skills"].append({"name": p.stem, "html": _md.render(_read_text(p) or "")})
    text = _read_text(d / "plan.md")
    if text is not None:
        out["plan"] = _md.render(text)
    reqs = _read_json(d / "method_requests.json")
    if reqs is not None:
        out["requests"] = reqs if isinstance(reqs, list) else []
    rep = _read_json(d / "discovery_report.json")
    if rep is not None:
        cands = []
        for c in rep.get("candidates") or []:
            if isinstance(c, dict):
                cands.append({k: c.get(k) for k in
                              ("rank", "name", "repo", "url", "stars", "last_push", "language",
                               "fit_score", "fit_notes", "pip_installable")})
        cands.sort(key=lambda c: (c.get("rank") is None, c.get("rank") or 0))
        install = rep.get("install") if isinstance(rep.get("install"), dict) else {}
        out["method"] = {"status": rep.get("status"), "error": rep.get("error"),
                         "chosen": rep.get("chosen"), "choice_reason": rep.get("choice_reason"),
                         "import_name": rep.get("import_name"),
                         "install_status": install.get("status"),
                         "model": rep.get("scout_model"), "elapsed_sec": rep.get("elapsed_sec"),
                         "candidates": cands}
    return JSONResponse(out)


def _stop(request: Request):
    run = _run_dir(request.path_params["rid"])
    if run is None:
        return JSONResponse({"error": "No such run."}, status_code=404)
    info = _status(run)
    if not info["active"]:
        return JSONResponse({"error": "This run is not running."}, status_code=409)
    pid = (_read_json(run / "run.json") or {}).get("pid")
    (run / "stop.json").write_text(json.dumps({"requested": time.time()}))
    try:
        os.killpg(pid, signal.SIGINT)          # the agent cleans up and writes usage.json
    except (ProcessLookupError, TypeError):
        return JSONResponse({"ok": True})

    def force():
        time.sleep(STOP_GRACE_SECONDS)
        if _status(run)["status"] == "stopping":
            try:
                os.killpg(pid, signal.SIGKILL)  # a long code cell can outlast the interrupt
            except ProcessLookupError:
                pass
    threading.Thread(target=force, daemon=True).start()
    return JSONResponse({"ok": True})


def _file(request: Request):
    run = _run_dir(request.path_params["rid"])
    if run is None:
        return JSONResponse({"error": "No such run."}, status_code=404)
    target = (run / request.path_params["path"]).resolve()
    if run.resolve() not in target.parents or not target.is_file() or \
            target.name in BOOKKEEPING:
        return JSONResponse({"error": "No such file."}, status_code=404)
    headers = {
        # Files are written by model-generated code, so never let one run script in the
        # page's origin: an SVG or HTML file opened directly is shown with scripts disabled.
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; "
                                   "style-src 'unsafe-inline'",
        "X-Content-Type-Options": "nosniff",
    }
    if request.query_params.get("download"):
        return FileResponse(target, filename=target.name, headers=headers)
    return FileResponse(target, headers=headers)


# --------------------------------------------------------------------------- access code

_DENIED = """<!doctype html><meta charset="utf-8"><title>ConTexture</title>
<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;
color:#333"><h2>Access code needed</h2><p>Open the full address printed in the terminal where
<code>serve.py</code> is running. It ends with <code>?token=...</code>.</p></body>"""


class AccessCode(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        given = request.query_params.get("token")
        if given and secrets.compare_digest(given, Settings.token):
            response = RedirectResponse(url=request.url.path or "/", status_code=303)
            response.set_cookie(Settings.cookie, Settings.token, httponly=True,
                                samesite="strict")
            return response
        held = request.cookies.get(Settings.cookie, "")
        if held and secrets.compare_digest(held, Settings.token):
            return await call_next(request)
        return HTMLResponse(_DENIED, status_code=403)


def build_app() -> Starlette:
    routes = [
        Route("/", _index),
        Route("/api/config", _config),
        Route("/api/pick", _pick, methods=["POST"]),
        Route("/api/keys", _keys, methods=["GET"]),
        Route("/api/keys", _save_key, methods=["POST"]),
        Route("/api/keys/{var}", _remove_key, methods=["DELETE"]),
        Route("/api/runs", _list, methods=["GET"]),
        Route("/api/runs", _start, methods=["POST"]),
        Route("/api/runs/{rid}", _detail),
        Route("/api/runs/{rid}/log", _log),
        Route("/api/runs/{rid}/discovery", _discovery),
        Route("/api/runs/{rid}/stop", _stop, methods=["POST"]),
        Route("/api/runs/{rid}/files/{path:path}", _file),
        Mount("/static", StaticFiles(directory=WEB / "static")),
    ]
    return Starlette(routes=routes, middleware=[Middleware(AccessCode)])


def _free_port(host: str, first: int, tries: int = 30) -> int:
    """The first port from `first` that nothing else is listening on.

    On a shared login node another user's program may already hold the requested port, and
    the server would otherwise report success and then fail to start.
    """
    for port in range(first, first + tries):
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"No free port between {first} and {first + tries - 1}. "
                     "Choose another with --port.")


def _can_open_browser() -> bool:
    """True on a computer with a screen. On a remote server Python may pick a text browser
    that would take over the terminal, so there the address is only printed."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="contexture serve",
                                     description="ConTexture in your browser.")
    parser.add_argument("--port", type=int, default=8765,
                        help="The first port to try; the next free one is used if it is taken.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Address to listen on. Keep the default unless you know you need "
                             "another; the page is protected only by its access code.")
    parser.add_argument("--runs-dir", default=str(Path.cwd() / "contexture-runs"),
                        help="Where each analysis gets its own folder.")
    parser.add_argument("--max-concurrent", type=int, default=1,
                        help="How many analyses may run at once. Each can use tens of GB of "
                             "memory.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Only print the address; do not open a browser.")
    args = parser.parse_args(argv)
    keys.load()

    Settings.runs_dir = Path(os.path.expanduser(args.runs_dir)).resolve()
    Settings.runs_dir.mkdir(parents=True, exist_ok=True)
    Settings.max_concurrent = max(1, args.max_concurrent)
    Settings.token = secrets.token_urlsafe(24)
    port = _free_port(args.host, args.port)
    # Cookies are shared by every port on one host, so the name carries the port: two pages
    # on one machine must not overwrite each other's access code.
    Settings.cookie = f"contexture_{port}"

    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{shown}:{port}/?token={Settings.token}"
    moved = f"(Port {args.port} was taken, so port {port} is used.)\n" if port != args.port else ""
    print(f"\nConTexture is running. Open this address in your browser:\n\n"
          f"    {url}\n\n{moved}"
          f"Runs are saved in {Settings.runs_dir}\n"
          "Press Ctrl+C to close the page. Analyses already running keep going.\n",
          flush=True)
    if not args.no_browser and _can_open_browser():
        # Opened a moment later, once the server is listening.
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(build_app(), host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
