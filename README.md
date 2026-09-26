# ConTexture

An autonomous agent for spatial multi-omics analysis. Give it a data file and a goal in plain
English. It writes and runs Python until the goal is met, then saves the result, the figures and a
full transcript of what it did. Everything runs on your own computer; only the requests to the
language model leave it.

## Install

You need [uv](https://docs.astral.sh/uv/) (macOS or Linux; on Windows, use WSL):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install ConTexture:

```bash
uv tool install git+https://github.com/anthony-qu/ConTexture
```

This gives you the `contexture` command. uv also fetches Python 3.13 if you do not have it. If
your terminal says `contexture` is not found, open a new terminal window, or run
`uv tool update-shell` once. To update later, run `uv tool upgrade contexture`.

## Use it in your browser

```bash
contexture
```

This opens the page in your browser. The first time, a **Model keys** panel asks for an API key
from a model provider (Anthropic, OpenAI, DeepSeek, Google Gemini or another). The key is saved
on your computer where only you can read it. Then you give the path to your data (an `.h5ad` or
`.h5mu` file), describe the goal, and watch each step as it runs: the code, its output and the
figures.

Each analysis gets its own folder in `contexture-runs/`, inside the folder you started
`contexture` from. An analysis keeps going if you close the browser.

The page's address ends with an access code. Anyone who has the full address can start analyses
with your API key, so do not share it.

## Or run it in the terminal

```bash
contexture run sample.h5ad "Cluster the spots, name the spatial domains, and save the result with the labels in obs['domain']."
```

| option | default | what it sets |
| --- | --- | --- |
| `--output-dir` | `contexture-output/` in the current folder | where results are written |
| `--model` | a model your saved key can use | any [LiteLLM](https://docs.litellm.ai/) model name |
| `--max-turns` | `30` | the turn budget for the run |

## Keys and models

Add, replace or remove a key from the **Model keys** button in the page's sidebar, or with
`contexture key` in the terminal. Saved keys live in `~/.config/contexture/keys.env`. A key set
in your shell environment (for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`
or `GEMINI_API_KEY`) or in a `.env` file in the current folder takes priority over a saved one.
You pay your model provider for what you use.

The agent runs the code it writes without a sandbox, so work on a copy of your data.

## Develop

```bash
git clone https://github.com/anthony-qu/ConTexture.git
cd ConTexture
uv sync
uv run contexture
```

Dependencies are pinned to the versions ConTexture was tested with; change a pin deliberately.
