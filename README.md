# ConTexture

An autonomous agent for spatial multi-omics analysis. Give it a data file and a goal in plain
English. It writes and runs Python until the goal is met, then saves the result, the figures and a
full transcript of what it did.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/anthony-qu/ConTexture.git
cd ConTexture
uv sync
```

Create a file named `.env` in the same folder, holding the API key for your model provider:

```
ANTHROPIC_API_KEY=sk-...
```

Models are named with [LiteLLM](https://docs.litellm.ai/) strings, so other providers work too.
Set the matching key instead (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, ...).

## Run

```bash
uv run python agent.py <data> "<goal>" [--output-dir DIR] [--model MODEL]
```

For example:

```bash
uv run python agent.py visium.h5ad \
  "find spatially variable genes and identify spatial domains" \
  --output-dir results/visium
```

The input is an `.h5ad` (AnnData) or `.h5mu` (MuData) file. Name the outputs you want in the
goal, for example "save the result with domain labels in `obs['domain']`".

Everything is written to `--output-dir`: the result object, the figures, and `dialog_log.txt`,
the full transcript with every code block the agent ran and its output.

| option | default | what it sets |
| --- | --- | --- |
| `--output-dir` | `output/` in this folder | where results are written |
| `--model` | `anthropic/claude-sonnet-4-6` | any LiteLLM model string |
| `--max-turns` | `30` | the turn budget for the run |

The agent runs the code it writes without a sandbox, so work on a copy of your data.
