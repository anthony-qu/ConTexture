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
on your computer where only you can read it. Then you pick your data (an `.h5ad` or `.h5mu`
file, or a folder of them) with the **Choose file** button, which opens your computer's own file
window, or type its path; describe the goal; and watch each step as it runs: the code, its
output and the figures. The data is read where it is, never copied.

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
| `--discovery` | off | method discovery (below) |
| `--evolve` | off | skill evolution (below; needs `--discovery`) |
| `--discovery-model` | the same as `--model` | the model for the data reporter, the skill maker and the method discovery agent |

## Method discovery and skill evolution

Both are off by default. On the page they are the two switches under **Before the analysis**; in
the terminal they are `--discovery` and `--evolve`. With them on, a run goes through these stages
before the analysis starts, and the page's **Discovery** tab shows each one as it finishes:

1. **Data report.** A data reporter reads the data and writes what it finds.
2. **Skill maker** (skill evolution only). For an assay that no skill covers, it composes a new
   skill from the existing skills and the platform transformations, tests the code on the data,
   and adds the skill to this run's menu.
3. **Plan.** A planner writes the analysis plan and names any step that needs a method that is
   not installed.
4. **Method discovery agent** (only when the plan named such a step). It searches Europe PMC and
   GitHub, ranks the candidates, installs its choice and tests it. The analysis then starts with
   the plan and the installed method.

Where a discovered method is installed matters, because published methods pin library versions
that often conflict with a current analysis stack. Run this once:

```bash
contexture setup-discovery
```

It needs conda (for example [Miniforge](https://conda-forge.org/download/)) and builds a small
conda environment, `omics-discovery-min`, that holds only the agent framework. Each discovery run
that installs a method then works in a fresh copy of it, deleted when the run ends. Without
conda, a discovered method is installed beside the run inside the analysis environment's
versions, which is fine for most methods; the page says which of the two will happen.

A method discovery run takes longer than a plain one: the stages above have time budgets of
6, 25 and 30 minutes, and the environment copy takes a few minutes. A `GITHUB_TOKEN` in the
environment or in `.env` lifts GitHub's rate limit for the search. The paper's runs used
`anthropic/claude-opus-5` for the data reporter, the skill maker and the method discovery agent;
`--discovery-model` sets that.

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

Every package, direct or indirect, is pinned in `pyproject.toml` to the version ConTexture was
tested with, because `uv tool install` resolves afresh and ignores `uv.lock`. The indirect pins
are generated: after changing a direct pin, run `uv lock`, then `python pin_from_lock.py`, then
`uv lock` again, and test.
