"""Phase 3 — switchable orchestrator + modality-specialist topology.

`build_root_agent(cfg, model, hooks)` returns the single agent the Runner drives:

  - topology == "flat"          -> EXACTLY today's single OmicsAgent. This path is
                                   byte-identical to the pre-Phase-3 construction, so
                                   the frozen flat_baseline numbers stay valid.
  - topology == "orchestrated"  -> an Orchestrator that dispatches per-modality
                                   preparation to a GENERIC ModalitySpecialist via
                                   Agent.as_tool, and performs the cross-modal step
                                   itself.
  - topology == "adaptive"      -> the SAME graph as "orchestrated", but the agent
                                   decides at runtime which topology to actually
                                   use, from the data in front of it. See below.

Why as_tool, not handoffs: as_tool runs the sub-agent via Runner.run under the
hood and returns its output to the caller, so the orchestrator KEEPS control and
can fan out to several specialists and reconvene. Handoffs transfer control
permanently — the wrong shape here.

State is shared for free. The execute_python REPL namespace (tools._repl_namespace)
is a module global, and as_tool does not sandbox the process — every specialist's
execute_python hits the SAME namespace. So the orchestrator loads the MuData once
and specialists mutate mdata['rna'], mdata['atac'], ... in place. The ledger (also
module-global) observes the shared object regardless of which agent ran the code.

── Adaptive routing (2026-07-25) ─────────────────────────────────────────────
`orchestrated` is TOLD its data is co-assayed; every role prompt asserts "two or
more modalities" and dispatch is an unconditional step. That is correct for the
measured co-assay arms and wrong for a deployed system, which gets handed either
an .h5ad or an .h5mu. On single-modality data the orchestrated topology degenerates
to a supervisor with one worker: same work as flat, plus an agent hop, plus an
integration step with no referent — paid for out of the turn budget that the
known completion-failure mode already competes for.

`adaptive` fixes that with TWO layers, because a prompt alone is not a guarantee:

  1. AGENT TURN — the orchestrator's routing clause (prompts._ORCH_ROUTING) makes
     INSPECT mandatory and requires it to print a `ROUTING:` line naming the path.
     This is what makes the decision the AGENT's, visible in the trace, and not a
     switch the harness flipped before launch.

  2. MECHANISM — `_routing_guard` wraps the delegation tools and re-derives the
     modality count from the REPL namespace itself at call time. Ground truth
     from the object, not the model's claim about it. Below the threshold the
     tool returns a rejection and NO sub-agent is started.

So the guarantee is one-directional and exact: on single-modality data a modality
specialist can never be spawned, whatever the model believes or says. The other
direction (multi-modal data SHOULD fan out) is prompt-led — a model that ignores
it just behaves like the flat agent, which is a weaker result, not a wrong one.
Forcing that direction would need tool_choice pinning, which would break the
agent's ability to finish the run.

The guard is applied ONLY for `adaptive`. `orchestrated` keeps its exact
pre-adaptive construction so Checkpoint B stays comparable.
"""
import dataclasses

from agents import Agent, RunConfig
from agents.model_settings import ModelSettings
from agents.extensions.models.litellm_provider import LitellmProvider

from . import ledger
from . import prompts
from . import tools

# Turn budgets for the NESTED as_tool runs. The SDK defaults nested runs to
# max_turns=10; per-modality prep and integration need more headroom, and the
# orchestrator itself keeps the outer max_turns passed to Runner.run.
_SPECIALIST_MAX_TURNS = 18


# ⭐ include_usage=True IS WHAT MAKES TOKEN ACCOUNTING WORK, AND ITS ABSENCE IS SILENT.
# We drive the agent with `Runner.run_streamed`. On the STREAMING path the LiteLLM model only
# sends `stream_options={"include_usage": ...}` when `model_settings.include_usage` is set;
# left at its default of None it sends nothing, the provider returns no usage block, and the
# SDK fills `Usage()` — all zeros. Nothing errors. Measured 2026-08-26: a 3-call run recorded
# 3 calls and 0 tokens. A cost figure built on that would have read as free.
# It changes the REQUEST metadata only, never sampling, so no arm's behaviour moves.
_USAGE_SETTINGS = ModelSettings(include_usage=True)


# 🔴 gpt-5.6-luna REJECTS FUNCTION TOOLS WHEN reasoning_effort IS SET, AND LITELLM SETS IT.
# LiteLLM attaches a reasoning_effort to gpt-5* models by default, and the chat-completions
# endpoint then answers:
#     "Function tools with reasoning_effort are not supported for gpt-5.6-luna"
# Our agent has nothing BUT function tools, so every call fails and the run makes zero model
# calls. Measured 2026-08-27: the F2a luna probe died in 18 s and the go/no-go gate then
# skipped all 19 remaining units, so one bad parameter cost the whole rung in 39 seconds.
# A bare curl to the same model works — the parameter is added by the client, not asked for.
# `reasoning_effort="none"` is accepted and returns tool calls; None and "minimal" both fail.
# Keyed on the model id rather than applied globally, so no other backbone's request changes.
# ⭐ CORRECTED: the RESPONSES ROUTE, not reasoning_effort="none". OpenAI's error names both
# escapes and they are NOT equivalent — "none" turns the model's thinking OFF, which is a
# weaker configuration than every other rung runs in and would make Luna look worse than it
# is. Measured on one question: responses route 38 reasoning tokens / 127 output; "none" 0 and
# 43. litellm 1.85 in THIS venv already carries the bridge, so no environment change is needed
# (an earlier claim that it was too old was wrong). Prefixing the model with `responses/` is
# the per-model trigger; the alternative env flag would reroute every OpenAI call in the
# process. `_MODEL_ROUTE` rewrites only the string sent to litellm — the recorded model id,
# and therefore the bundle label, is untouched.
_MODEL_QUIRKS: dict[str, dict] = {}
_MODEL_ROUTE = {"gpt-5.6-luna": "openai/responses/gpt-5.6-luna",
                "gpt-5.6-sol": "openai/responses/gpt-5.6-sol",
                "gpt-5.6-terra": "openai/responses/gpt-5.6-terra"}


def route_model(model: str) -> str:
    """The string litellm should be called with. Identity for every non-GPT-5.6 backbone."""
    return _MODEL_ROUTE.get(model.split("/")[-1], model)


# 💸 ANTHROPIC DOES NOT CACHE A PROMPT UNLESS ASKED, AND THIS AGENT RESENDS THE WHOLE
# TRANSCRIPT EVERY TURN. DeepSeek's cache is automatic (92% of input was served from it,
# measured over 20 BiomniBench units). Anthropic's is opt-in: a request-level
# `cache_control: {"type": "ephemeral"}` makes the API cache the longest cacheable prefix
# (tools -> system -> messages) so the next turn re-reads it at about a tenth of the input
# price and pays full price only for what is new. Measured 2026-09-17 without it: the MALT_S100
# run with the analysis agent on claude-opus-5 made 168 calls, 11.3 M input tokens, 0 cached,
# and exhausted the account's balance before writing analysis.md.
# Mechanism: the Agents SDK spreads `ModelSettings.extra_args` into `litellm.acompletion(**kw)`;
# litellm 1.85.1's Anthropic transformation lists `cache_control` among its supported params and
# passes a dict value through to the request body unchanged (checked offline with
# `AnthropicConfig().transform_request`). Keyed on the `anthropic/` prefix, so no other
# provider's request changes. Request metadata only: no sampling parameter moves, so no arm's
# behaviour moves, and the usage record gains `cached_input_tokens` > 0 as the visible check.
_ANTHROPIC_CACHE = {"cache_control": {"type": "ephemeral"}}


def _settings_for(model) -> ModelSettings:
    """Usage accounting for every model, Anthropic prompt caching, plus any per-model workaround."""
    name = str(model or "")
    extra: dict = {}
    quirk = _MODEL_QUIRKS.get(name.split("/")[-1])
    if quirk:
        extra.update(quirk)
    if name.startswith("anthropic/"):
        extra.update(_ANTHROPIC_CACHE)
    if not extra:
        return _USAGE_SETTINGS
    return dataclasses.replace(_USAGE_SETTINGS, extra_args=extra)


settings_for = _settings_for   # the name discovery.py and skillmaker.py import (lazily, inside their run functions)


def _nested_run_config(model: str) -> RunConfig:
    """The #1 wiring gotcha: nested as_tool runs default to the SDK's OpenAI
    provider. Without an explicit LitellmProvider run_config they never reach
    Claude and the specialist silently fails. Every as_tool call gets this.

    ⚠ AND it must carry _USAGE_SETTINGS too. A specialist's calls are real spend; if only the
    outer RunConfig asked for usage, orchestrated and adaptive arms would under-report by
    exactly the sub-agent work that distinguishes them from flat."""
    return RunConfig(model_provider=LitellmProvider(), model_settings=_settings_for(model))


# ── adaptive routing: the mechanical half ─────────────────────────────────────
# Both delegation tools are cross-modal by definition and need >= 2 modalities.
_MIN_MODALITIES = 2


def inspect_shared() -> dict:
    """What is ACTUALLY loaded in the shared CodeAct REPL, read from the objects.

    Returns {"var", "kind", "mods", "n"} — n is the modality count (0 when nothing
    is loaded, 1 for a plain AnnData, len(mod) for a MuData).

    Deliberately re-derived from the namespace rather than taken from anything the
    model said: the routing guarantee must not depend on the model reporting its
    own inspection honestly or correctly.

    Reuses ledger's duck-typed predicates rather than re-implementing detection —
    a second detector is a second thing to drift. MuData is checked first for the
    same reason ledger._scan does: a MuData's modalities are themselves AnnData,
    so scanning AnnData first would see `mdata['rna']` as a standalone
    single-modality object and route a co-assay dataset down the single path.
    """
    ns = getattr(tools, "_repl_namespace", None) or {}
    items = [(k, v) for k, v in list(ns.items()) if not k.startswith("_")]

    for name, obj in items:
        try:
            if ledger._is_mudata(obj):
                mods = list(obj.mod)
                return {"var": name, "kind": "MuData", "mods": mods, "n": len(mods)}
        except Exception:
            continue

    for name, obj in items:
        try:
            if ledger._is_anndata(obj):
                return {"var": name, "kind": "AnnData", "mods": [], "n": 1}
        except Exception:
            continue

    return {"var": None, "kind": None, "mods": [], "n": 0}


def _refusal(tool_name: str, rec: dict) -> str:
    """What the model gets back instead of a sub-agent. Says what was observed,
    why the call was refused, and what to do instead — a rejection the run can
    recover from in one turn, not a dead end."""
    if rec["n"] == 0:
        return (
            f"ROUTING REFUSED — `{tool_name}` did not run and no sub-agent was started.\n"
            "No AnnData/MuData is loaded in the shared session yet, so the number of "
            "modalities is unknown and delegation cannot be routed.\n"
            "Do STEP 1 (INSPECT) first: load the data into a stable variable with "
            "execute_python, print the modalities and shapes, and print the ROUTING line."
        )
    mods = f", modalities {rec['mods']}" if rec["mods"] else ""
    return (
        f"ROUTING REFUSED — `{tool_name}` did not run and no sub-agent was started.\n"
        f"The shared session holds {rec['kind']} `{rec['var']}` with "
        f"n_modalities={rec['n']}{mods}. This is path=single: there is no second "
        "modality to prepare separately and nothing to integrate across.\n"
        "Prepare this one modality yourself with execute_python (load guidance with "
        "get_skill), then verify and write the deliverable. "
        f"Do not call `{tool_name}` again for this dataset."
    )


def _routing_guard(tool):
    """Gate a delegation tool on the REAL modality count. The hard half of the guarantee.

    Mutates `on_invoke_tool` in place rather than dataclasses.replace(): FunctionTool
    carries private fields (`_is_agent_tool`, `_agent_instance`, ...) that mark it as
    an agent-tool, and rebuilding the dataclass risks dropping one silently. We own
    this object exclusively — as_tool just built it for us.
    """
    inner = tool.on_invoke_tool
    name = tool.name

    async def _invoke(ctx, input_json: str):
        # Budget reserve, enforced at DISPATCH rather than at execution. Only the
        # orchestrator calls this tool, so refusing here cannot accidentally block the
        # agent that owns the deliverable — which is exactly what an earlier
        # execution-time version did (see tools._step_guard for that post-mortem).
        # Refusing a dispatch is also something an orchestrator handles well: it has
        # other options. Refusing a specialist mid-task just makes it retry.
        left = tools.steps_remaining()
        if left is not None and left <= tools._reserve():
            msg = (
                f"DISPATCH REFUSED — only {left} execution steps remain of "
                f"{tools._step_budget}, which are reserved for you to finish.\n"
                "Do not start another specialist. Integrate what has already been "
                "prepared, then write the final deliverable to disk yourself, now."
            )
            tools._append_dialog("[ROUTING]", f"REFUSED {name} — budget reserve ({left} left)")
            return msg

        rec = inspect_shared()
        if rec["n"] < _MIN_MODALITIES:
            tools._append_dialog(
                "[ROUTING]",
                f"REFUSED {name} — path=single (n_modalities={rec['n']}, "
                f"var={rec['var']}, kind={rec['kind']}); no sub-agent started",
            )
            return _refusal(name, rec)
        tools._append_dialog(
            "[ROUTING]",
            f"ALLOWED {name} — path=multi ({rec['kind']} `{rec['var']}`, "
            f"n_modalities={rec['n']}, modalities={rec['mods']})",
        )
        # Remember who dispatched, and put the acting-agent label back afterwards.
        # A nested as_tool run does not reliably fire on_agent_end, so without this the
        # log keeps attributing the orchestrator's own work to the specialist that has
        # already finished. This return is the one moment we know the specialist ended.
        dispatcher = tools._current_agent
        try:
            return await inner(ctx, input_json)
        finally:
            tools.restore_agent(dispatcher)

    tool.on_invoke_tool = _invoke
    return tool


def build_root_agent(cfg: dict, model: str, hooks=None) -> Agent:
    """The agent the Runner drives, selected by config — no `if arm == ...`.

    ⚠ The model string is routed ONCE here, so every Agent in the graph (root, specialist,
    orchestrator) is built with the same routed string. Routing only the root would leave
    sub-agents on the plain chat endpoint, which fails outright on gpt-5.6."""
    model = route_model(model)
    if cfg.get("topology", "flat") not in tools.MULTI_AGENT_TOPOLOGIES:
        # Flat: the exact current construction. Do NOT touch this branch — its
        # byte-identity is what assert_baseline_unchanged() protects.
        return Agent(
            name="OmicsAgent",
            instructions=prompts.build(cfg),
            tools=tools.build_tools(cfg),
            model=model,
        )
    return _build_orchestrated(cfg, model, hooks)


def _build_orchestrated(cfg: dict, model: str, hooks) -> Agent:
    # `adaptive` builds the identical graph and adds the runtime guard; the agents
    # it may dispatch have to exist before it knows whether it will dispatch them.
    guard = cfg.get("topology") == "adaptive"
    base_tools = tools.build_tools(cfg)   # [execute_python, get_skill] (+ arm knobs)

    # ONE generic specialist, called once per modality (parameterized by the
    # modality string in its input) — dataset-agnostic across RNA+protein,
    # RNA+ATAC, and the 4-modality object. No hardcoded rna/atac/prot agents.
    specialist = Agent(
        name="ModalitySpecialist",
        instructions=prompts.build_role("modality_specialist", cfg),
        tools=base_tools,
        model=model,
    )
    prepare_modality = specialist.as_tool(
        tool_name="prepare_modality",
        tool_description=(
            "Delegate per-modality preparation to a modality specialist. Call ONCE "
            "PER MODALITY. Pass a short instruction that names exactly ONE modality "
            "to prepare and the variable holding the shared object, e.g. \"Prepare "
            "the 'rna' modality of the shared object `mdata`: QC, normalize, HVG, "
            "PCA + neighbors.\" The specialist operates on the SHARED in-memory "
            "object, so its work persists for you and the other specialists."
        ),
        run_config=_nested_run_config(model),
        max_turns=_SPECIALIST_MAX_TURNS,
        hooks=hooks,
    )
    if guard:
        prepare_modality = _routing_guard(prepare_modality)

    # The orchestrator always owns the cross-modal step. A dedicated IntegrationAgent
    # alternative (knob `integration_owner`, arm `orchestrated_intagent`) was removed
    # 2026-07-26: it was never part of the `target` configuration being optimised.
    orch_tools = [prepare_modality, *base_tools]

    return Agent(
        name="Orchestrator",
        instructions=prompts.build_role("orchestrator", cfg),
        tools=orch_tools,
        model=model,
    )
