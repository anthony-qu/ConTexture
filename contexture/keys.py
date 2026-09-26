"""Where ConTexture finds model API keys, and the one-time question that saves one.

Keys are looked for in this order, and an earlier source is never overwritten by a later one:

1. variables already set in the environment;
2. a `.env` file in the folder the command is run from;
3. the user's own settings file, `~/.config/contexture/keys.env` (under `$XDG_CONFIG_HOME` when
   that is set).

Only `contexture key`, or the question asked when no key is found, writes the settings file, and
it is written so that only its owner can read it. The key never passes through the web page.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# (what the user is shown, the variable LiteLLM reads, a sensible default model for that key)
PROVIDERS = [
    ("Anthropic (Claude)", "ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-6"),
    ("OpenAI", "OPENAI_API_KEY", "openai/gpt-5.6-sol"),
    ("DeepSeek", "DEEPSEEK_API_KEY", "deepseek/deepseek-v4-flash"),
    ("Google Gemini", "GEMINI_API_KEY", "gemini/gemini-2.5-pro"),
]


def settings_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "contexture" / "keys.env"


def load() -> None:
    load_dotenv(Path.cwd() / ".env", override=False)
    load_dotenv(settings_file(), override=False)


def found() -> list[str]:
    """Names of the key variables that are set, never their values."""
    return sorted(k for k, v in os.environ.items() if k.endswith("_API_KEY") and v.strip())


def default_model() -> str:
    """The first provider, in PROVIDERS order, whose key is present."""
    for _, var, model in PROVIDERS:
        if os.environ.get(var, "").strip():
            return model
    return PROVIDERS[0][2]


def save(var: str, value: str) -> Path:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lines = []
    if path.exists():
        lines = [ln for ln in path.read_text().splitlines()
                 if ln.strip() and not ln.split("=", 1)[0].strip() == var]
    lines.append(f"{var}={value}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    return path


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
        if not var.endswith("_API_KEY") or not var.replace("_", "").isalnum():
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
    os.environ[var] = value
    print(f"Saved in {path}, readable only by you. Run `contexture key` to change it.\n")
    return True
