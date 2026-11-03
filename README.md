<p align="center"><img src="docs/banner.png" alt="ConTexture: a self-evolving agentic AI system for spatial multi-omics analysis that adapts to new, unseen assay technologies" width="100%"></p>

ConTexture is a self-evolving agentic AI system for spatial multi-omics analysis that can adapt
to new, unseen assay technologies.

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

![The ConTexture page](docs/screenshot.png)

Pick a data file (`.h5ad` or `.h5mu`, or a folder of them), describe the goal, choose a model,
and start. The first time, the page asks for an API key from a model provider; it is saved on
your computer. **Discovery mode** turns on method discovery and skill evolution. Each run gets
its own folder in `contexture-runs/`, inside the folder you started `contexture` from.

## Or run it in the terminal

```bash
contexture run sample.h5ad "Cluster the spots, name the spatial domains, and save the result with the labels in obs['domain']."
```

| option | default | what it sets |
| --- | --- | --- |
| `--output-dir` | `contexture-output/` in the current folder | where results are written |
| `--model` | a model your saved key can use | any [LiteLLM](https://docs.litellm.ai/) model name |
| `--max-turns` | `30` | the turn budget for the run |
| `--discovery` | off | method discovery |
| `--evolve` | off | skill evolution (needs `--discovery`) |
| `--discovery-model` | the same as `--model` | the model for the data reporter, the skill maker and the method discovery agent |

