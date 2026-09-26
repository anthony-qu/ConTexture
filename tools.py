import contextlib
import io
import os
import traceback
from pathlib import Path

from agents import function_tool

import ledger

_SKILLS_DIR = Path(__file__).parent / "skills"

# ── arm configuration ─────────────────────────────────────────────────────────
# The knob vocabulary is defined in code/analysis/wrappers/configs/arms.yaml.
#
# FLAT_BASELINE is the EXPERIMENTAL zero point: every knob off, and what
# `configure(None)` / `agent.main(config=None)` still resolve to. It is a
# measurement condition, not a recommendation — do not repoint it at the
# deployment default, or the recorded baseline stops describing the baseline
# (and _KNOB_DEFAULTS in run_arm.py, which arms inherit omitted knobs from,
# would silently shift with it).
FLAT_BASELINE: dict = {
    "ledger": False,            # P2b — not implemented yet
    "skills": "base",           # P2a: base | additional
    "topology": "flat",         # P3: flat | orchestrated | adaptive
    "selector": "none",         # P5 — not implemented yet
    "discovery": False,         # find + install a package before analysing (discovery.py)
    "evolve": False,            # skill maker: compose a skill for an unseen assay before
                                # analysing (skillmaker.py). Requires discovery. 2026-09-15.
}
# `discovery` (2026-08-04) is deliberately NOT part of build_tools() or of any prompt
# fragment. When it is ON, a separate scout agent runs BEFORE the analysis agent and
# appends a pointer to its findings to the GOAL TEXT — the analysis agent's system
# prompt and tool list are byte-identical in both modes. That is what keeps "off is
# absence" true here without a single branch in the analysis path.
#
# Adding a knob changes `config_sha` for every arm (it hashes the resolved config
# dict). That is provenance metadata, not behaviour: prompt_sha, skills_sha and the
# tool list are all unchanged, so nothing about what a pre-existing arm DOES has
# moved. Same class of change as when `topology` was added and `integration_owner`
# removed.
# NOTE: `integration_owner` was removed 2026-07-26 along with the dedicated
# IntegrationAgent. The orchestrator now always owns the cross-modal step, so the knob
# had a single legal value. See prompts.roles() / topology._build_orchestrated().

_config: dict = dict(FLAT_BASELINE)

# The topology values that build a MULTI-AGENT graph. Defined here, next to
# FLAT_BASELINE, because tools.py is the canonical vocabulary module and nothing
# imports it in a way that could cycle — prompts.py, topology.py, agent.py and
# run_arm.py all read this one set rather than repeating the literal, so they
# cannot disagree about whether `adaptive` is multi-agent.
#
# `adaptive` is orchestrated-shaped: it builds the same agents but decides at
# RUNTIME, from the data, whether to dispatch them (see topology._routing_guard).
MULTI_AGENT_TOPOLOGIES = ("orchestrated", "adaptive")

# What a REAL USER gets: `uv run python agent.py <data> "<goal>"`. The deployment
# default is `adaptive`, because a user hands over either an .h5ad or an .h5mu and
# the system should not need to be told which — see topology.py's routing section.
#
# Deliberately SEPARATE from FLAT_BASELINE rather than a change to it: the two
# answer different questions ("what should this system do by default" vs "what is
# the measurement zero point"), and collapsing them would let a deployment
# preference silently redefine every recorded delta.
#
# It must stay equal to the `adaptive` arm in arms.yaml — asserted by
# results/phase3/smoke_adaptive.py, so the deployed default and the measured arm
# cannot drift into being different things with the same name.
DEPLOYMENT_DEFAULT: dict = {
    "ledger": True,
    "skills": "additional",
    "topology": "adaptive",
    "selector": "none",                    # P5, not implemented
    "discovery": False,                    # opt-in: costs a network round trip and
                                           # ~5 min before any analysis starts, so a
                                           # plain `uv run python agent.py` must not
                                           # pay for it. Turned on by the
                                           # `target_discovery` arm.
    "evolve": False,                       # opt-in, and only with discovery: the
                                           # `target_evolve` arm / `--evolve`.
}

# Persistent namespace across all execute_python calls within one Runner.run()
# session. Common scientific libraries are pre-imported on first use.
_repl_namespace: dict = {}
_repl_initialized: bool = False

_dialog_log_path: str | None = None

# Skill evolution (2026-09-15). The directory holding the skills the SKILL MAKER wrote for
# THIS run (`<bundle>/discovery/evolved/`), set by skillmaker.attach(). Like
# _dialog_log_path it is a per-run destination set explicitly by the entry point, so
# configure() does NOT clear it -- but _skill_files() reads it ONLY when the live config
# has `evolve` on, which is what stops a live directory reaching another arm assembled in
# the same process (the same regression the discovery note had; see prompts._MARKERS).
_evolved_dir: Path | None = None


def set_evolved_dir(path: str | None) -> None:
    global _evolved_dir
    _evolved_dir = Path(path) if path else None


def evolved_dir() -> Path | None:
    return _evolved_dir

# P3 — the stack of agents currently acting (root ... innermost), maintained by
# the run hooks. Used ONLY to tag the dialog log in the orchestrated topology; in
# flat mode the tag is suppressed (see _agent_tag) so flat logs stay byte-identical.
# A STACK, not a scalar: when a specialist's nested as_tool run ends, control
# returns to its parent, so the tag must pop back — otherwise the orchestrator's
# own integration/write steps would be mislabeled as the last specialist.
_agent_stack: list[str] = []
_current_agent: str | None = None


def push_agent(name: str) -> None:
    """A nested agent run has started (on_agent_start)."""
    global _current_agent
    _agent_stack.append(name)
    _current_agent = name


def pop_agent() -> None:
    """A nested agent run has ended (on_agent_end) — restore its parent."""
    global _current_agent
    if _agent_stack:
        _agent_stack.pop()
    _current_agent = _agent_stack[-1] if _agent_stack else None


def restore_agent(name: str | None) -> None:
    """Force the acting agent back to `name`, discarding anything above it.

    `on_agent_end` does not reliably fire for a nested as_tool run, so the stack can
    be left holding a specialist that has already finished — after which every later
    line in the dialog log is attributed to the wrong agent. The one moment we KNOW a
    specialist has ended is when its dispatch tool returns, so topology._routing_guard
    calls this with whoever dispatched it.

    This used to be worse than a mislabelled log: an earlier budget reserve asked the
    stack "am I a specialist?" and, because of this, locked the orchestrator out of
    running any code. Nothing functional depends on the stack now, but a trace that
    lies about which agent acted is still worth fixing.
    """
    global _current_agent
    if name is None:
        _agent_stack.clear()
        _current_agent = None
        return
    if name in _agent_stack:
        del _agent_stack[_agent_stack.index(name) + 1:]
    else:
        _agent_stack.clear()
        _agent_stack.append(name)
    _current_agent = name


def _agent_tag() -> str:
    """`" @<agent>"` in a multi-agent topology, `""` everywhere else.

    Gated on topology, not just on _current_agent being set: the flat run also
    fires on_agent_start (for the single OmicsAgent), so gating on topology is
    what keeps the flat dialog log byte-identical to the pre-Phase-3 log.

    `adaptive` is tagged like `orchestrated` even when it routes to the
    single-modality path — the trace should show WHICH agent acted, and on that
    path the answer (always the Orchestrator) is exactly the fact worth recording.
    """
    if _current_agent and _config.get("topology") in MULTI_AGENT_TOPOLOGIES:
        return f" @{_current_agent}"
    return ""


# ── shared step budget (fixes: nested runs were unbounded) ────────────────────
# The SDK's max_turns bounds ONE Runner.run. In an orchestrated/adaptive topology
# every nested as_tool run gets its OWN max_turns, which never counts against the
# root's — so the declared budget did not bound the arm at all. Measured before the
# fix: 43, 42 and 56 execute_python calls against declared caps of 20 and 45.
#
# This counter is shared by every agent in the graph (it is a module global, and
# as_tool does not sandbox the process), so it bounds the WHOLE run. Set from the
# task's declared budget by agent.main().
#
# OFF BY DEFAULT: `_step_budget is None` means execute_python behaves exactly as it
# did before, so flat arms — already bounded by max_turns — are untouched.
_step_budget: int | None = None
_step_count: int = 0


def set_step_budget(n: int | None) -> None:
    """Bound total execute_python calls across ALL agents in this run."""
    global _step_budget, _step_count
    _step_budget = n
    _step_count = 0


def _reserve() -> int:
    """Steps held back for whoever owns the deliverable."""
    return max(3, (_step_budget or 0) // 4)


def _step_guard() -> str | None:
    """None when the call may proceed; a message to return to the agent when the
    shared budget is spent. Counts the call it permits.

    The reserve exists because in a multi-agent topology **the agent that spends the
    budget is not the agent that owns the deliverable**. Observed on the first bounded
    run: the specialist burned all 20 steps on per-modality preparation, and control
    returned to the orchestrator — the only agent allowed to write the result — with
    nothing left. Warning the specialist does not help; its role prompt explicitly
    forbids it from writing the deliverable.

    So specialists are cut off at the reserve line and told to hand back, leaving the
    last quarter of the budget for the orchestrator to integrate and save.
    """
    global _step_count
    if _step_budget is None:
        return None

    left = _step_budget - _step_count

    # NOTE: there is deliberately NO per-agent rule here. An earlier version refused
    # nested agents once the reserve was reached, detecting "nested" as _agent_stack
    # depth > 1 — and the stack never pops back (on_agent_end does not restore the
    # parent for as_tool runs), so after the first specialist ran, the ORCHESTRATOR was
    # permanently misclassified as nested and refused by its own reserve. That produced
    # a deadlock: the only agent allowed to write the deliverable could not run code.
    # The agent's own words from the trace: "the system is preventing me from running
    # execute_python because it has 'reserved' the budget for me".
    # The reserve now lives at DISPATCH time instead (topology._routing_guard), which
    # only the orchestrator ever reaches, so it needs no notion of who is running.
    if left <= 0:
        return (
            "STEP BUDGET EXHAUSTED — this run has used all "
            f"{_step_budget} of its execution steps, so no further code will run.\n"
            "Write your final deliverable NOW using only what you already know. "
            "If you cannot, state plainly what is missing and stop."
        )
    _step_count += 1
    return None


def steps_remaining() -> int | None:
    return None if _step_budget is None else max(0, _step_budget - _step_count)


def _budget_notice() -> str:
    """A warning appended to the tool result as the budget runs low — empty otherwise.

    Without this the bound is a trap: the agent hits a hard wall and is told to write
    its deliverable, but writing a file *requires* execute_python, which is exactly what
    has just been refused. Observed on the first bounded run: the refusal fired seven
    times because the agent had no way to comply.

    So the warning has to arrive while there are still steps left to act on it. It
    states a fact and leaves the decision to the agent — the same discipline as the
    provenance ledger: report, never judge.
    """
    left = steps_remaining()
    if left is None or left > max(3, _step_budget // 4):
        return ""
    if left == 0:
        return ""          # the refusal path already says everything
    return (f"\n\n[BUDGET] {left} execution step(s) remain of {_step_budget}. "
            f"Save your deliverable to disk now — once the budget is spent no further "
            f"code will run, and anything not yet written is lost.")


def configure(cfg: dict | None = None) -> dict:
    """Set the arm config for this run and reset all per-run REPL state.

    The single reset point, and the reason it exists: the state below is module
    global. That is safe at one-arm-per-process (how run_arm.py works today) but
    silently wrong the moment a sweep loops arms inside one process — arm n+1
    would inherit arm n's REPL objects, and the contaminated delta would be
    invisible in the results. So the reset is unconditional, not opt-in.

    Call this before build_tools() and prompts.build().

    `_dialog_log_path` is deliberately NOT reset: it is an output destination that
    both entry points set explicitly per run, and clearing it here would silently
    drop the [ARM] provenance block run_arm.py writes before the agent starts.
    """
    global _config, _repl_namespace, _repl_initialized, _current_agent, _step_count
    ledger.reset()
    _current_agent = None
    _agent_stack.clear()
    _step_count = 0          # the budget itself is set per-run by agent.main()
    unknown = set(cfg or {}) - set(FLAT_BASELINE)
    if unknown:
        raise ValueError(
            f"Unknown config knob(s): {sorted(unknown)}. "
            f"Known knobs: {sorted(FLAT_BASELINE)}. (Did arms.yaml drift from tools.FLAT_BASELINE?)"
        )
    _config = dict(FLAT_BASELINE) | dict(cfg or {})

    # The skill maker is a discovery-mode agent: it needs the data report the reporter
    # writes and the environment sequence bootstrap() runs. `evolve` without `discovery`
    # would run nothing and report a null delta as a result, so it is refused.
    if _config.get("evolve") and not _config.get("discovery"):
        raise ValueError("evolve=True requires discovery=True (the skill maker runs inside "
                         "the discovery sequence; see skill-evolve/PLAN.md).")

    # An empty skill tier would make this arm silently identical to the flat
    # baseline — and a null delta from an arm that never differed is worse than a
    # crash, because it reads as a real result. Fail loudly instead.
    tier = _config.get("skills", "base")
    if tier not in ("base", "none") and not any((_SKILLS_DIR / tier).glob("*.md")):
        raise ValueError(
            f"skills='{tier}' but {_SKILLS_DIR / tier}/ contains no .md files — this arm "
            f"would run as flat_baseline and report a meaningless null delta."
        )

    _repl_namespace = {}
    _repl_initialized = False
    return dict(_config)


def get_config() -> dict:
    return dict(_config)


def set_dialog_log(path: str) -> None:
    global _dialog_log_path
    _dialog_log_path = path


def set_output_dir(path: str) -> None:
    plots_dir = f"{path}/plots"
    os.makedirs(plots_dir, exist_ok=True)
    _repl_namespace["output_dir"] = path
    _repl_namespace["plots_dir"] = plots_dir


def _append_dialog(section: str, content: str) -> None:
    if _dialog_log_path:
        with open(_dialog_log_path, "a") as f:
            f.write(f"{section}\n{content.strip()}\n\n")


def _ensure_initialized() -> None:
    global _repl_initialized
    if _repl_initialized:
        return
    exec(
        "import os\n"
        "import numpy as np\n"
        "import pandas as pd\n"
        "import scanpy as sc\n"
        "import anndata as ad\n"
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        # squidpy is the one pre-import allowed to fail, and only ever does in a
        # discovery run. There, the environment is resolved around a DISCOVERED method's
        # version pins, which can land a squidpy that does not work with the dask it was
        # given (measured: squidpy 1.6.2 + dask 2026.7.1 raises on import). Since the
        # REPL pre-imports run before every execute_python call, an unguarded failure
        # there kills the whole run over a convenience alias.
        #
        # In `.venv` squidpy always imports, so this is behaviour-preserving: `sq` is
        # bound exactly as before and nothing else changes. Only the failure path is new.
        "try:\n"
        "    import squidpy as sq\n"
        "except Exception as _sq_err:\n"
        "    sq = None\n"
        "    print(f'[note] squidpy unavailable in this environment ({_sq_err}); '\n"
        "          f'`sq` is None. Everything else is unaffected.')\n",
        _repl_namespace,
    )
    _repl_namespace["agent_message"] = lambda msg: None
    _repl_initialized = True


@function_tool
def execute_python(code: str) -> str:
    """Execute Python code in a persistent session.

    Variables assigned in one call are available in the next.
    np, pd, sc, ad, plt, os, sq are pre-imported.

    Use print() to return values — bare expressions produce no output.
    Save figures with plt.savefig(); plt.show() is a no-op.
    Returns the captured stdout, or a traceback on error.
    """
    # Shared across every agent in the graph; a no-op when no budget is set, so the
    # flat arms' behaviour is unchanged. See set_step_budget().
    exhausted = _step_guard()
    if exhausted is not None:
        _append_dialog(f"[BUDGET]{_agent_tag()}", exhausted)
        return exhausted

    _ensure_initialized()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, _repl_namespace)
        output = buf.getvalue() or "(no output — use print() to return values)"
    except Exception:
        output = traceback.format_exc()
    tag = _agent_tag()   # "" in flat mode -> logs byte-identical to pre-Phase-3
    _append_dialog(f"[CODE]{tag}", code)
    _append_dialog(f"[OUTPUT]{tag}", output)

    # P2b — off => this block never runs and `output` is byte-identical to the
    # pre-ledger implementation. "Off is absence, not a branch."
    if _config.get("ledger"):
        state = ledger.observe(_repl_namespace)   # "" when nothing changed
        if state:
            _append_dialog(f"[STATE]{tag}", state)
            output = f"{output}\n\n{state}"

    # Empty unless a budget is set AND it is running low, so flat arms are unchanged.
    notice = _budget_notice()
    if notice:
        _append_dialog(f"[BUDGET]{tag}", notice.strip())
        output = f"{output}{notice}"

    return output


# ── skills ────────────────────────────────────────────────────────────────────

def _skill_tiers() -> list[str]:
    """Which skill directories this arm exposes. `base` alone == the flat baseline.

    `base/` is FROZEN: it is the three single-omics guides the Phase-1 comparison ran
    with. Everything new — extra basics, spatial, co-assay — lands in `additional/`,
    so the baseline keeps describing what it described.
    """
    return ["base"] if _config.get("skills", "base") == "base" else ["base", "additional"]


def _skill_files() -> dict[str, Path]:
    """name -> path, for the tiers this arm exposes."""
    found: dict[str, Path] = {}
    for tier in _skill_tiers():
        for path in sorted((_SKILLS_DIR / tier).glob("*.md")):
            found[path.stem] = path
    # Skill evolution: this run's evolved skills join the menu, gated on the CONFIG, not
    # on the directory being set. `glob("*.md")` is one level deep on purpose -- proposed
    # transforms live in evolved/transforms/ and are never exposed. A name that collides
    # with a hand-written skill is skipped (write_skill refuses such names, so this is a
    # second guard, not the first).
    if _config.get("evolve") and _evolved_dir is not None and _evolved_dir.is_dir():
        for path in sorted(_evolved_dir.glob("*.md")):
            if path.stem not in found and path.stem != "README":
                found[path.stem] = path
    return found


@function_tool
def get_skill(skill_name: str | None = None) -> str:
    """Load a methodology skill guide, or list all available skills.

    Two-step usage:
      1. Call with no argument to get the menu of available skills and their
         descriptions. Do this during the LOAD SKILLS phase after planning.
      2. Call again with a specific skill_name to load the full guide for each
         skill relevant to your plan. Make one call per relevant skill type.

    If no skills are relevant to the task, skip this tool entirely after step 1.

    Args:
        skill_name: Name of the skill to load. Omit to list available skills.
    """
    files = _skill_files()
    available = sorted(files)
    tag = _agent_tag()   # "" in flat mode -> logs byte-identical to pre-Phase-3

    if skill_name is None:
        lines = ["Available skills:"]
        for name in available:
            text_lines = files[name].read_text().split("\n")
            use_for = next(
                (l[len("use_for:"):].strip() for l in text_lines[:5] if l.startswith("use_for:")),
                text_lines[0].lstrip("# ").strip(),
            )
            lines.append(f"  - \"{name}\": {use_for}")
        menu = "\n".join(lines)
        _append_dialog(f"[SKILL]{tag}", f"MENU\n{menu}")
        return menu

    if skill_name in files:
        content = files[skill_name].read_text()
        _append_dialog(f"[SKILL]{tag}", f"LOADED: {skill_name}")
        return content

    msg = f"Skill '{skill_name}' not found. Available: {available}."
    _append_dialog(f"[SKILL]{tag}", f"NOT FOUND: {skill_name} — available: {available}")
    return msg


# ── tool registry ─────────────────────────────────────────────────────────────

def build_tools(cfg: dict | None = None) -> list:
    """The tool list for an arm.

    Composed, not branched: a component that is off contributes nothing, rather
    than contributing an inert stub. That is what makes an "off" knob a genuine
    no-op instead of a confound.
    """
    cfg = cfg if cfg is not None else _config
    tools = [execute_python]
    if cfg.get("skills", "base") != "none":
        tools.append(get_skill)
    return tools


# Back-compat: the flat baseline's tool set, as it was before arms existed.
all_tools = [execute_python, get_skill]
