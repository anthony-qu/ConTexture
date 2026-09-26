"""Where ConTexture finds model API keys, and how a key is saved.

Keys are looked for in this order, and an earlier source is never overwritten by a later one:

1. variables already set in the environment (for example an `export` line in a shell profile);
2. a `.env` file in the folder the command is run from;
3. the user's own settings file, `~/.config/contexture/keys.env` (under `$XDG_CONFIG_HOME` when
   that is set).

A key is saved to the settings file from the web page's "Model keys" panel, by `contexture key`,
or by the question `contexture run` asks when no key is found. The file is written so that only
its owner can read it. A saved key is never sent back to the page; the page is told only where a
key came from and its last four characters.
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# (what the user is shown, the variable LiteLLM reads, a sensible default model for that key)
PROVIDERS = [
    ("Anthropic (Claude)", "ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-6"),
    ("OpenAI", "OPENAI_API_KEY", "openai/gpt-5.6-sol"),
    ("DeepSeek", "DEEPSEEK_API_KEY", "deepseek/deepseek-v4-flash"),
    ("Google Gemini", "GEMINI_API_KEY", "gemini/gemini-2.5-pro"),
]
KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]*_API_KEY$")

# Where each key in the environment came from: "environment", "env_file" or "settings".
SOURCES: dict[str, str] = {}


def settings_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "contexture" / "keys.env"


def load() -> None:
    SOURCES.clear()
    for name, value in os.environ.items():
        if KEY_NAME.match(name) and value.strip():
            SOURCES[name] = "environment"
    for source, path in (("env_file", Path.cwd() / ".env"), ("settings", settings_file())):
        if not path.is_file():
            continue
        for name, value in dotenv_values(path).items():
            if KEY_NAME.match(name) and (value or "").strip() and name not in SOURCES:
                SOURCES[name] = source
        load_dotenv(path, override=False)


def found() -> list[str]:
    """Names of the key variables that are set, never their values."""
    return sorted(k for k, v in os.environ.items() if KEY_NAME.match(k) and v.strip())


def default_model() -> str:
    """The first provider, in PROVIDERS order, whose key is present."""
    for _, var, model in PROVIDERS:
        if os.environ.get(var, "").strip():
            return model
    return PROVIDERS[0][2]


def status() -> list[dict]:
    """Every known provider plus any other key that is set: its source and last four characters."""
    rows = []
    known = {var for _, var, _ in PROVIDERS}
    names = [(label, var) for label, var, _ in PROVIDERS] + \
            [(var[: -len("_API_KEY")].replace("_", " ").title(), var)
             for var in found() if var not in known]
    for label, var in names:
        value = os.environ.get(var, "").strip()
        rows.append({"label": label, "var": var,
                     "source": SOURCES.get(var) if value else None,
                     "hint": f"...{value[-4:]}" if len(value) >= 8 else ("set" if value else "")})
    return rows


def _write(lines: list[str]) -> Path:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(f"{ln}\n" for ln in lines))
    os.chmod(path, 0o600)
    return path


def _saved_lines(without: str | None = None) -> list[str]:
    path = settings_file()
    if not path.exists():
        return []
    return [ln for ln in path.read_text().splitlines()
            if ln.strip() and ln.split("=", 1)[0].strip() != without]


def save(var: str, value: str) -> Path:
    """Save a key to the settings file and use it from now on in this process."""
    if not KEY_NAME.match(var):
        raise ValueError(f"{var!r} is not a key variable name")
    value = value.strip()
    if not value or "\n" in value:
        raise ValueError("the key is empty or spans several lines")
    path = _write(_saved_lines(without=var) + [f"{var}={value}"])
    os.environ[var] = value
    SOURCES[var] = "settings"
    return path


def remove(var: str) -> bool:
    """Remove a key from the settings file. A key from the environment is left alone."""
    if not KEY_NAME.match(var):
        return False
    before = _saved_lines()
    after = _saved_lines(without=var)
    if len(after) == len(before):
        return False
    _write(after)
    if SOURCES.get(var) == "settings":
        os.environ.pop(var, None)
        SOURCES.pop(var, None)
    return True


def ask_and_save(always: bool = False) -> bool:
    """Ask for one key in the terminal and save it. Returns True if a key was saved."""
    if not always and found():
        return False
    if not sys.stdin.isatty():
        if always:
            print("`contexture key` asks for the key interactively; run it in a terminal window.",
                  file=sys.stderr)
        else:
            print("No model API key was found. Run `contexture key` in a terminal to add one, or "
                  "set a variable such as ANTHROPIC_API_KEY before starting.", file=sys.stderr)
        return False
    if not always:
        print("\nConTexture needs an API key for a language model. You pay the provider for "
              "what you use.")
    print("\nWhich provider is your key from?")
    for i, (label, var, _) in enumerate(PROVIDERS, 1):
        print(f"  {i}. {label}")
    print(f"  {len(PROVIDERS) + 1}. Another provider (you type the variable name)")
    choice = input(f"Enter 1-{len(PROVIDERS) + 1}: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(PROVIDERS):
        var = PROVIDERS[int(choice) - 1][1]
    elif choice == str(len(PROVIDERS) + 1):
        var = input("Variable name (for example MISTRAL_API_KEY): ").strip().upper()
        if not KEY_NAME.match(var):
            print("That is not a key variable name. Nothing was saved.")
            return False
    else:
        print("Nothing was saved.")
        return False
    value = getpass.getpass("Paste the key (it is not shown as you type): ").strip()
    if not value:
        print("No key entered. Nothing was saved.")
        return False
    path = save(var, value)
    print(f"Saved in {path}, readable only by you. Run `contexture key` to change it.\n")
    return True
