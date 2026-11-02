import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from agents import Agent, Runner, RunConfig, MaxTurnsExceeded, RunHooks
from agents.extensions.models.litellm_provider import LitellmProvider

from . import prompts
import json as _json

from . import tools
from . import topology


class _ToolLogger(RunHooks):
    """Observer only. It logs and counts; it never influences what the agent does.

    ⭐ TOKEN ACCOUNTING LIVES HERE, NOT IN A WRAPPER, and the reason is that this is the ONLY
    place the real numbers exist. `on_llm_end` receives the SDK's own ModelResponse with a
    populated `usage`; a wrapper outside the process can do no better than scrape a log, which
    silently under-counts nested `Agent.as_tool` runs (orchestrated/adaptive arms make several
    model calls the parent never prints). Per-call rows are kept as well as the total so a
    later cost figure can be recomputed if a price changes, and so an anomalous single call is
    visible rather than averaged away.

    ⚠ It records usage for OUR agent only. Competing agents run in their own processes and
    must write the same `usage.json` schema from their own wrappers — `generic_agent_wrapper`
    can read the `claude` CLI's reported usage, which F2c needs and F2a does not.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []
        self.stream_path: str | None = None   # set once output_dir is known


    async def on_llm_end(self, context, agent, response) -> None:
        # Never let accounting break a paid run: a missing field costs a row, not the analysis.
        try:
            u = getattr(response, "usage", None)
            if u is None:
                return
            # ⚠ input_tokens ALONE CANNOT PRICE A RUN. Every provider we use bills a cached
            # input token at a fraction of a fresh one — DeepSeek returns
            # prompt_cache_hit_tokens / prompt_cache_miss_tokens outright, Anthropic charges
            # cache reads at a tenth and cache writes at a premium — and these runs are
            # cache-heavy by construction, since the whole transcript is resent every turn.
            # A Claude CLI run in this project billed $2.42 with 2.5M of it cache reads. So
            # `cached_tokens` is split out here; cost = (input - cached) * miss_rate +
            # cached * hit_rate + output * out_rate. `reasoning_tokens` is recorded too: it is
            # billed as output and DeepSeek V4 has thinking always on, so it is never zero.
            ind = getattr(u, "input_tokens_details", None)
            outd = getattr(u, "output_tokens_details", None)
            self.calls.append({
                "agent": getattr(agent, "name", None),
                "requests": getattr(u, "requests", None),
                "input_tokens": getattr(u, "input_tokens", None),
                "cached_input_tokens": getattr(ind, "cached_tokens", None),
                "output_tokens": getattr(u, "output_tokens", None),
                "reasoning_tokens": getattr(outd, "reasoning_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            })
            # 🔴 APPEND EACH CALL AS IT HAPPENS. The summary is written in a `finally`, and a
            # `finally` DOES NOT RUN ON SIGKILL — which is exactly how an out-of-memory kill
            # ends a run. Measured 2026-08-26: a BiomniBench unit was OOM-killed (rc=137) after
            # 217 s and 8 model calls, and its usage.json did not exist. The expensive runs are
            # the ones most likely to be killed, so losing precisely those would bias any cost
            # figure downward. This line-per-call file survives a kill; the summary can be
            # rebuilt from it.
            if self.stream_path:
                with open(self.stream_path, "a") as fh:
                    fh.write(_json.dumps(self.calls[-1]) + "\n")
        except Exception:
            pass

    def usage_summary(self) -> dict:
        def tot(k):
            return sum(c[k] or 0 for c in self.calls if c.get(k) is not None)
        cached = tot("cached_input_tokens")
        return {
            "model_calls": len(self.calls),
            "requests": tot("requests"),
            "input_tokens": tot("input_tokens"),
            "cached_input_tokens": cached,
            # the billable split: what a provider charges full price for
            "uncached_input_tokens": tot("input_tokens") - cached,
            "output_tokens": tot("output_tokens"),
            "reasoning_tokens": tot("reasoning_tokens"),
            "total_tokens": tot("total_tokens"),
            "per_call": self.calls,
        }

    async def on_agent_start(self, context, agent) -> None:
        # Push the acting agent so tools.py can tag its [CODE]/[OUTPUT]/[SKILL]
        # writers by agent. on_agent_end pops it, so when a specialist's nested
        # run returns the tag falls back to the orchestrator. In flat mode the tag
        # is suppressed (tools._agent_tag gates on topology), so nothing here
        # changes the flat dialog log — the [AGENT-START] line is only written
        # when orchestrated, keeping flat_baseline byte-identical.
        tools.push_agent(agent.name)
        if tools.get_config().get("topology") in tools.MULTI_AGENT_TOPOLOGIES:
            tools._append_dialog("[AGENT-START]", agent.name)

    async def on_agent_end(self, context, agent, output) -> None:
        # A (possibly nested) agent run finished — restore its parent as current.
        tools.pop_agent()

    async def on_tool_start(self, context, agent, tool) -> None:
        import json as _json
        name = getattr(context, "tool_name", None) or getattr(tool, "name", str(tool))
        raw = getattr(context, "tool_arguments", "") or ""
        try:
            parsed = _json.loads(raw)
            args = _json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            args = raw
        tools._append_dialog("[TOOL]", f"{name}(\n{args}\n)")


def _extract_message_text(item) -> str:
    content = getattr(getattr(item, "raw_item", None), "content", None) or []
    parts = [block.text for block in content if hasattr(block, "text")]
    return "\n".join(parts).strip()

load_dotenv()

# OpenAI
# DEFAULT_MODEL = "gpt-4o"
# DEFAULT_MODEL = "gpt-4o-mini"
# Anthropic (requires ANTHROPIC_API_KEY)
# DEFAULT_MODEL = "anthropic/claude-opus-4-7"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
# DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
# Google (requires GEMINI_API_KEY)
# DEFAULT_MODEL = "gemini/gemini-2.5-pro"
# DEFAULT_MODEL = "gemini/gemini-2.5-flash"
# DEFAULT_MODEL = "gpt-4o"


async def main(
    data_path: str,
    goal: str,
    output_dir: str,
    model: str,
    max_turns: int = 30,
    config: dict | None = None,
) -> None:
    """Run the agent.

    `config` is one ablation arm's toggles (see analysis/wrappers/configs/arms.yaml).
    It decides which skills, system prompt and topology this run gets.

    `config=None` still resolves to the FLAT BASELINE — unchanged, because
    run_arm.py's measurement contract and the "off is absence" discipline both rest
    on all-knobs-off meaning the zero point. The CLI below does NOT rely on that
    default: it passes tools.DEPLOYMENT_DEFAULT (adaptive) explicitly, so the
    deployed behaviour is a visible choice at the entry point rather than a
    redefinition of the baseline.
    """
    # configure() FIRST: it resets the REPL state and normalises the config, and
    # set_output_dir() below writes into the namespace it clears.
    cfg = tools.configure(config)

    # Bound the WHOLE graph, not just the root. max_turns below bounds one Runner.run;
    # in an orchestrated/adaptive topology each nested as_tool run gets its own budget
    # that never counts against the root's, so the declared limit did not bound the arm
    # at all (43/42/56 execute_python calls measured against caps of 20 and 45).
    # Flat arms are already bounded by max_turns, so they are left alone — which also
    # keeps their behaviour byte-identical.
    if cfg.get("topology") in tools.MULTI_AGENT_TOPOLOGIES:
        tools.set_step_budget(max_turns)

    # ONE hooks instance, shared by the root run AND every nested as_tool run, so
    # the whole topology writes to one dialog log. Built before the agent because
    # orchestrated specialists need it threaded into their as_tool run_config.
    hooks = _ToolLogger()

    # Flat -> exactly today's single OmicsAgent (byte-identical).
    # Orchestrated -> Orchestrator + modality specialist(s) (+ integration agent).
    agent = topology.build_root_agent(cfg, model, hooks=hooks)

    prompt = (
        f"Goal: {goal}\n"
        f"Data: {data_path}\n"
        f"Output directory: {output_dir}\n\n"
        f"Begin the analysis."
    )

    tools.set_output_dir(output_dir)
    tools.set_dialog_log(f"{output_dir}/dialog_log.txt")
    if hasattr(hooks, "stream_path"):
        hooks.stream_path = f"{output_dir}/usage.jsonl"

    from datetime import datetime
    tools._append_dialog(
        "[SESSION]",
        f"timestamp : {datetime.now().isoformat(timespec='seconds')}\n"
        f"model     : {model}\n"
        f"data      : {data_path}\n"
        f"output_dir: {output_dir}\n"
        f"goal      : {goal}\n"
        f"config    : {cfg}\n"
        f"prompt_sha: {prompts.sha(cfg)}\n"
        f"fragments : {prompts.fragment_names(cfg) or '(none — base prompt verbatim)'}\n"
        f"skills    : {sorted(tools._skill_files())}\n"
        f"tools     : {[t.name for t in tools.build_tools(cfg)]}",
    )

    try:
        streamed = Runner.run_streamed(
            agent,
            prompt,
            run_config=RunConfig(model_provider=LitellmProvider(),
                                 model_settings=topology._settings_for(model)),
            max_turns=max_turns,
            hooks=hooks,
        )
        async for event in streamed.stream_events():
            if (
                event.type == "run_item_stream_event"
                and event.name == "message_output_created"
            ):
                text = _extract_message_text(event.item)
                if text:
                    tools._append_dialog("[AGENT]", text)
        print(streamed.final_output)
    except MaxTurnsExceeded:
        print("Agent stopped: max turns reached. Pipeline may be incomplete.")
        print(f"Check partial outputs in: {output_dir}")
    finally:
        # ⚠ finally, NOT the success path. A run that hits the turn cap or dies mid-way has
        # still SPENT its tokens, and a cost figure that silently omits the expensive failures
        # would understate exactly the runs worth knowing about.
        try:
            import json as _json
            summary = hooks.usage_summary() if hasattr(hooks, "usage_summary") else {}
            summary.update({"model": model, "output_dir": output_dir,
                            "config": cfg, "max_turns": max_turns})
            with open(f"{output_dir}/usage.json", "w") as fh:
                _json.dump(summary, fh, indent=2)
            tools._append_dialog(
                "[USAGE]",
                f"model_calls: {summary.get('model_calls')}  "
                f"input: {summary.get('input_tokens')} "
                f"(cached {summary.get('cached_input_tokens')})  "
                f"output: {summary.get('output_tokens')} "
                f"(reasoning {summary.get('reasoning_tokens')})  "
                f"total: {summary.get('total_tokens')}")
        except Exception as e:
            print(f"[usage] could not write usage.json: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="contexture run",
                                     description="Run one ConTexture analysis in the terminal.")
    parser.add_argument("data_path", help="Path to input .h5ad or .h5mu file")
    parser.add_argument("goal", help='Research goal, e.g. "identify cell types"')
    # Results go where the user is working, never inside the installed package.
    parser.add_argument("--output-dir", default=str(Path.cwd() / "contexture-output"))
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LiteLLM model string")
    parser.add_argument(
        "--topology", default=None, choices=["flat", "orchestrated", "adaptive"],
        help="Override the deployment default (adaptive: the agent inspects the data "
             "and routes itself). 'flat' = single agent; 'orchestrated' = always "
             "dispatch per modality, which is wrong for single-modality input.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=30,
        help="Turn budget for the whole graph. run_arm.py uses 45 for benchmark arms; "
             "match it when comparing a CLI run against one.",
    )
    parser.add_argument(
        "--discovery", action="store_true",
        help="Method discovery: before the analysis, a data reporter describes the data, a "
             "planner writes the plan and names any step that needs a method not installed, "
             "and a method discovery agent searches the literature and GitHub for one, installs "
             "and tests it. With conda and `contexture setup-discovery`, the install goes into a "
             "fresh environment copy for this run only. Off by default.",
    )
    parser.add_argument(
        "--evolve", action="store_true",
        help="Skill evolution (requires --discovery): before the analysis, a skill maker "
             "composes a methodology guide for an assay no skill covers, from the existing "
             "skills and the platform transformations, tests its code on the data, and adds it "
             "to this run's skill menu. Off by default.",
    )
    parser.add_argument(
        "--discovery-model", default=None, metavar="MODEL",
        help="The model for the data reporter, the skill maker and the method discovery agent "
             "(the planner always runs on --model). Default: the same as --model. The paper's "
             "runs used anthropic/claude-opus-5 for these three. A DISCOVERY_REPORTER_MODEL, "
             "SKILL_MAKER_MODEL or DISCOVERY_SCOUT_MODEL variable set in the environment wins "
             "over the default, and this option wins over both.",
    )
    args = parser.parse_args()
    if args.evolve and not args.discovery:
        parser.error("--evolve requires --discovery (the skill maker runs inside the "
                     "discovery sequence)")

    # The CLI is the DEPLOYMENT entry point, so it opts in to the deployment default
    # explicitly. Measured arms never come through here — they go through
    # analysis/wrappers/run_arm.py, which resolves them from arms.yaml.
    cfg = dict(tools.DEPLOYMENT_DEFAULT)
    if args.topology:
        cfg["topology"] = args.topology
    if args.discovery:
        cfg["discovery"] = True
    if args.evolve:
        cfg["evolve"] = True

    # --- discovery: the pre-agent sequence, and the environment switch --------
    # Imported lazily INSIDE the branch, so an off-run never touches this module — not
    # even to import it. That is what makes "off is absence" mechanical here rather
    # than a promise.
    #
    # This lives at the deployment entry point rather than in the benchmark wrapper
    # because it IS deployment behaviour: someone running the agent from the command
    # line with discovery on must get the same sequence an arm gets. run_arm.py calls
    # the same bootstrap() rather than keeping its own copy.
    if cfg.get("discovery"):
        import os
        import sys

        from . import discovery, discoveryenv                        # noqa: E402
        # The three discovery agents' models. `discovery.py` reads these variables at run
        # time and falls back to its recorded constant (claude-opus-5); in the installed
        # package the fallback is instead the analysis model, so a user with one key can run
        # the whole sequence. An explicit --discovery-model replaces all three.
        for var in ("DISCOVERY_REPORTER_MODEL", "SKILL_MAKER_MODEL", "DISCOVERY_SCOUT_MODEL"):
            if args.discovery_model:
                os.environ[var] = args.discovery_model
            else:
                os.environ.setdefault(var, args.model)
        if not discovery.in_discovery_env():
            print("[DISCOVERY] " + discoveryenv.explain())   # also exports CONDA_EXE when found
        tools.set_output_dir(args.output_dir)
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        tools.set_dialog_log(f"{args.output_dir}/dialog_log.txt")
        env_python = discovery.bootstrap(
            data_path=args.data_path, goal=args.goal, output_dir=args.output_dir,
            evolve=bool(cfg.get("evolve")), model=args.model)
        if env_python:
            print(f"[DISCOVERY] re-executing under {env_python}")
            # The measured agent restarts itself by file path from a checkout on sys.path. An
            # installed package has neither, so the restart runs `python -m contexture.agent`
            # in the clone with a copy of this package on PYTHONPATH (discoveryenv.exec_in).
            discoveryenv.exec_in(env_python, args.output_dir, sys.argv[1:])
            # exec_in does not return. bootstrap() short-circuits on the way back in.

        # Skill evolution: the maker ran before the switch (inside bootstrap) and wrote
        # to disk; read it back here, in whichever interpreter this now is, and expose
        # it. Lazy import inside the branch, like discovery itself.
        if cfg.get("evolve"):
            from . import skillmaker                                  # noqa: E402
            ev = skillmaker.attach(args.output_dir)
            print(f"[EVOLVE] status={(ev or {}).get('status', 'no_report')} "
                  f"skills={sorted((ev or {}).get('skills', {}))}")

        report = asyncio.run(discovery.run_scout(
            goal=args.goal, data_path=args.data_path, output_dir=args.output_dir,
            model=args.model))
        # Into the orchestrator's SYSTEM PROMPT, not the goal: a discovered package is
        # an environment fact, so it belongs with the other "what is installed" lines.
        prompts.set_discovery_note(discovery.scout_note(report))
        (Path(args.output_dir) / "discovery" / "prompt_note.txt").write_text(
            (prompts.discovery_note() or "") + "\n")      # the note as given; the prompt is never logged
        print(f"[DISCOVERY] status={report['status']} "
              f"chosen={report.get('chosen') or '(none)'}")

    try:
        asyncio.run(main(
            data_path=args.data_path,
            goal=args.goal,
            output_dir=args.output_dir,
            model=args.model,
            max_turns=args.max_turns,
            config=cfg,
        ))
    finally:
        # The input was made read-only before the reporter ran and stayed that way for
        # the whole analysis. A hard kill skips this; `chmod -R u+w <data>` reverses it.
        if cfg.get("discovery"):
            from . import discovery                                  # noqa: E402
            discovery.restore_input(args.output_dir)
