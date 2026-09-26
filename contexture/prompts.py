"""Assemble the system prompt for an ablation arm.

ONE base prompt + optional fragments, concatenated in a fixed order — never one
.txt file per arm. Two full copies of a prompt drift apart (this repo already has
`codeAct.txt` and `codeAct+tools.txt` as evidence), and a wording difference that
isn't part of the component under test shows up in the results as a component
effect. That contamination is invisible in the numbers.

`prompts/codeAct.txt` IS the base — deliberately not renamed, so the flat baseline
keeps reading the byte-identical file it always read. With no fragments active,
build() returns that file verbatim; `run_arm.py` asserts it.
"""
import hashlib
import re
from pathlib import Path

from . import tools   # for MULTI_AGENT_TOPOLOGIES only — tools.py never imports prompts,
               # so this direction cannot cycle. Keeping the set in ONE place is
               # what stops roles()/topology.py/_agent_tag() from disagreeing about
               # which topologies are multi-agent.

PROMPT_DIR = Path(__file__).parent / "prompts"
BASE_PROMPT = PROMPT_DIR / "base_prompt.txt"
ROLE_DIR = PROMPT_DIR / "roles"

# ── clause markers: ONE prompt, filled per arm ────────────────────────────────
# 2026-08-09. Every arm now assembles from prompts/base_prompt.txt. The base carries
# `{{marker}}` placeholders; each is either replaced by a clause file or, when its
# component is off, the WHOLE LINE is deleted. There is no second prompt document.
#
# This replaced a separate roles/orchestrator.txt. The two files had been written
# independently and had drifted: three instructions differed for reasons that had
# nothing to do with delegation (the output-directory guard and the "a check you run
# is a gate" rule were flat-only; the write-and-confirm step was orchestrator-only).
# That silently confounded the topology ablation — the step from `substrate` to
# `orchestrated` changed four things, not one. One document cannot drift from itself.
#
# `discovery_clause` is the odd one out: its text is not a file. The method scout
# produces it at run time and run_arm.py passes it to set_discovery_note() before the
# agent is built. With discovery off the value is None and the line is dropped.
CLAUSE_DIR = PROMPT_DIR / "clauses"


def _is_multi(cfg: dict) -> bool:
    return cfg.get("topology") in tools.MULTI_AGENT_TOPOLOGIES


# marker name -> (predicate over cfg, clause file stem or None for a runtime value).
# Order here is irrelevant; position in base_prompt.txt is what places the text.
_MARKERS: dict = {
    # 🔴 GATE ON THE ARM AS WELL AS ON THE NOTE (fixed 2026-08-18). This predicate used
    # to read `bool(discovery_note())` alone, and `_discovery_note` is a MODULE GLOBAL.
    # So once a scout had run, the note was substituted into EVERY arm assembled in that
    # process -- including `flat_baseline`, the anchor every ablation delta is measured
    # against. `verify_prompt_injection.py` asserts it does not, and that check was
    # failing.
    # It never bit a recorded run, because a run is one arm in one process and
    # `set_discovery_note` is only called on a discovery arm. That is process hygiene,
    # not absence, and this file's whole discipline is that "off" means absence by
    # construction. No recorded prompt_sha moves: with discovery off there was never a
    # note to leak in the first place.
    # 2026-09-15: the same marker now also carries the SKILL MAKER's note, gated on
    # cfg["evolve"] in the same way (see _note_for). One marker, because both are facts
    # about what this run's environment holds and both sit in the "installed" list.
    "discovery_clause":  (lambda cfg: bool(_note_for(cfg)), None),
    "topology_clause_1": (_is_multi, "topology_clause_1"),
    "topology_clause_2": (_is_multi, "topology_clause_2"),
    "topology_clause_3": (_is_multi, "topology_clause_3"),
    "adapt_clause_1":    (lambda cfg: cfg.get("topology") == "adaptive", "adapt_clause_1"),
    "ledger_clause_1":   (lambda cfg: bool(cfg.get("ledger")), "ledger_clause_1"),
}


# ── discovery note (2026-08-05) ───────────────────────────────────────────────
# When discovery mode finds a package, the orchestrator is told about it IN ITS SYSTEM
# PROMPT rather than in the goal text — a discovered package is an environment fact, so
# it belongs beside the other "what is installed" lines, not inside the task statement.
#
# The FILE is never rewritten. `roles/orchestrator.txt` carries a static
# `{{DISCOVERY_NOTE}}` sentinel, and substitution happens at assembly time:
#   discovery on AND a package was found -> the sentinel becomes the note
#   otherwise                            -> the sentinel LINE is removed entirely
# so with discovery off the assembled prompt is byte-identical to what it was before
# the sentinel existed, and `orchestrated`/`target` keep their recorded prompt_sha.
DISCOVERY_SENTINEL = "{{DISCOVERY_NOTE}}\n"

_discovery_note: str | None = None


def set_discovery_note(note: str | None) -> None:
    """Record what the method scout found, for injection into the orchestrator prompt.

    Set once per run by run_arm.py, before the agent is built. None (the default, and
    what every non-discovery arm sees) means the sentinel line is simply dropped.
    """
    global _discovery_note
    _discovery_note = note or None


def discovery_note() -> str | None:
    return _discovery_note


# ── skill-evolution note (2026-09-15) ─────────────────────────────────────────
# Same mechanism, second fact: when the skill maker wrote a skill for this run, the
# analysis agent is told so in its system prompt, beside the scout's line. Gated on
# cfg["evolve"] for the same reason the scout note is gated on cfg["discovery"]: the
# note is a module global, and an arm without the knob must never see it.
_evolve_note: str | None = None


def set_evolve_note(note: str | None) -> None:
    """Record what the skill maker wrote, for injection into the system prompt.
    Set once per run by skillmaker.attach(). None means the line is simply absent."""
    global _evolve_note
    _evolve_note = note or None


def evolve_note() -> str | None:
    return _evolve_note


def _note_for(cfg: dict) -> str:
    """The text the discovery marker carries for this arm: the scout's line, the skill
    maker's line, both, or nothing -- each present only when its knob is on AND it has
    something to say. Empty string means the marker LINE is dropped."""
    parts = []
    if cfg.get("discovery") and discovery_note():
        parts.append(discovery_note().strip("\n"))
    if cfg.get("discovery") and cfg.get("evolve") and evolve_note():
        parts.append(evolve_note().strip("\n"))
    return "\n".join(parts)


def _clause_text(stem: str) -> str:
    """Read one clause. A missing file is a hard error, never an empty clause — an
    empty clause would silently drop instructions from a live arm."""
    path = CLAUSE_DIR / f"{stem}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt clause missing: {path}. base_prompt.txt references it via a "
            f"{{{{{stem}}}}} marker."
        )
    return path.read_text()


def _fill_markers(text: str, cfg: dict) -> str:
    """Resolve every {{marker}} in the base prompt.

    ON  -> replaced by its clause, continuation lines indented to the marker's own
           column so the surrounding bullet list still reads straight.
    OFF -> the ENTIRE LINE is removed. Substituting an empty string would leave a bare
           "- " bullet, which reads as an instruction that went missing.
    An unknown marker raises: leaving `{{typo}}` in a live system prompt is exactly the
    failure this table exists to prevent.
    """
    out = []
    for line in text.split("\n"):
        m = re.search(r"\{\{([^}]+)\}\}", line)
        if not m:
            out.append(line)
            continue
        name = m.group(1).strip()
        if name not in _MARKERS:
            raise KeyError(
                f"base_prompt.txt uses an unknown marker {{{{{name}}}}}. "
                f"Known: {sorted(_MARKERS)}"
            )
        predicate, stem = _MARKERS[name]
        if not predicate(cfg):
            continue
        body = _note_for(cfg) if stem is None else _clause_text(stem)
        body = (body or "").strip("\n")
        if not body:
            continue
        prefix = line[:m.start()]
        indent = " " * len(prefix)
        lines = [l.rstrip() for l in body.split("\n")]
        pad = min((len(l) - len(l.lstrip()) for l in lines[1:] if l.strip()), default=0)
        out.append(prefix + lines[0].lstrip())
        out.extend(indent + l[pad:] if l.strip() else "" for l in lines[1:])
    return "\n".join(out)


def build(cfg: dict) -> str:
    """The system prompt for this arm: base_prompt.txt with its markers resolved.

    For `flat_baseline` every marker is off, so this is the base file with all six
    marker lines removed — which IS the flat baseline prompt by definition now.
    """
    return _fill_markers(BASE_PROMPT.read_text(), cfg).rstrip() + "\n"


# ── Phase 3: role prompts for the orchestrated topology ───────────────────────
# Role prompts carry ROLE + SCOPE only, never methodology — that stays in skills/
# via get_skill, so the topology delta measures coordination, not extra knowledge.

def roles(cfg: dict) -> list[str]:
    """The role prompts an arm actually uses. Empty for flat arms (they use the
    single codeAct.txt prompt via build()); the orchestrated set for multi-agent
    arms (`orchestrated` and `adaptive`), gated by who owns the integration step.

    `adaptive` uses the SAME three roles: it decides at runtime whether to dispatch
    them, so the agents it may call must exist from the start.
    """
    if cfg.get("topology") not in tools.MULTI_AGENT_TOPOLOGIES:
        return []
    return ["orchestrator", "modality_specialist"]


def build_role(role: str, cfg: dict) -> str:
    """The system prompt for one role in an orchestrated arm.

    `orchestrator` is NOT a separate document any more. It is build(cfg) — the same
    base_prompt.txt every arm uses, with the topology markers switched on. That is the
    whole point of the 2026-08-09 change: roles/orchestrator.txt was a second copy of
    the shared instructions and it had drifted from the base in three places that had
    nothing to do with delegation, which quietly confounded the topology ablation.

    Every other role keeps its own file, because a specialist's prompt is genuinely a
    different document rather than the base plus a clause.
    """
    if role == "orchestrator":
        return build(cfg)
    path = ROLE_DIR / f"{role}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Role prompt missing: {path}. Every orchestrated role except "
            f"`orchestrator` needs a .txt in prompts/roles/."
        )
    return path.read_text()


def build_scout_role() -> str:
    """The method scout's prompt (discovery mode). Read by discovery.run_scout().

    Deliberately NOT routed through build_role(): the scout is not part of the
    analysis topology — it runs before the analysis agent, has its own tools, and
    never touches the data — so it takes no orchestrator clauses and is not listed
    by roles(). Keeping it out of roles() is also what leaves every existing arm's
    prompt_sha byte-identical.
    """
    path = ROLE_DIR / "method_scout.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Scout prompt missing: {path}. discovery=True needs it."
        )
    return path.read_text()


def build_reporter_role() -> str:
    """The data reporter's prompt (discovery mode). Read by discovery.run_reporter().

    Kept out of roles() for the same reason the scout is: it runs before the analysis
    topology exists, has its own single tool, and takes no orchestrator clauses. It
    reaches sha() only through _effective_prompt_text's discovery branch, so no
    pre-existing arm's prompt_sha moves.
    """
    path = ROLE_DIR / "data_reporter.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Data reporter prompt missing: {path}. discovery=True needs it."
        )
    return path.read_text()


def build_skill_maker_role() -> str:
    """The skill maker's prompt (discovery mode with evolve on). Read by
    skillmaker.run_skill_maker(). Kept out of roles() for the same reason the scout and
    the reporter are: it runs before the analysis topology exists, has its own tools,
    and takes no orchestrator clauses. It reaches sha() only through the evolve branch
    of _effective_prompt_text, so no pre-existing arm's prompt_sha moves."""
    path = ROLE_DIR / "skill_maker.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Skill maker prompt missing: {path}. evolve=True needs it."
        )
    return path.read_text()


def build_planner_role() -> str:
    """The planner's prompt (discovery mode, version 2). Read by discovery.run_planner().
    Kept out of roles() like the scout and the reporter: it runs before the analysis
    topology exists, has its own tools, and takes no orchestrator clauses. It reaches
    sha() only through the discovery branch of _effective_prompt_text, so no
    pre-existing arm's prompt_sha moves; the two discovery arms' sha moved on
    2026-09-17 when this was folded in, which is recorded in the verifiers."""
    path = ROLE_DIR / "planner.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Planner prompt missing: {path}. discovery=True needs it."
        )
    return path.read_text()


def _effective_prompt_text(cfg: dict) -> str:
    """What this arm's agent(s) are actually instructed with — the basis for sha().

    Flat: the single assembled prompt (byte-identical to codeAct.txt), so flat
    arms keep their existing prompt_sha. Orchestrated: the concatenated role
    prompts, so two orchestrated arms (e.g. the two ownership variants) can be
    proven to differ only where intended, and never collide with a flat sha.

    Discovery appends the scout AND data-reporter prompts ON TOP of whichever of those
    applies, and ONLY when the knob is on — so a discovery arm gets a provably distinct
    sha while every arm that does not use it keeps the sha it already had. Both are
    folded in because both are agents the arm actually runs; leaving the reporter out
    would let its prompt be rewritten without any run's provenance showing a change.
    """
    rs = roles(cfg)
    text = build(cfg) if not rs else "\n\n".join(
        f"=== {r} ===\n{build_role(r, cfg)}" for r in rs)
    if cfg.get("discovery"):
        text = (f"{text}\n\n=== method_scout ===\n{build_scout_role()}"
                f"\n\n=== data_reporter ===\n{build_reporter_role()}"
                f"\n\n=== planner ===\n{build_planner_role()}")
    # The skill maker is folded in only when its knob is on, so `target_evolve` gets a
    # provably distinct sha while `target_discovery` keeps the one it has (b616bcc58737).
    if cfg.get("discovery") and cfg.get("evolve"):
        text = f"{text}\n\n=== skill_maker ===\n{build_skill_maker_role()}"
    return text


def sha(cfg: dict) -> str:
    """Short digest of this arm's effective prompt(s) — recorded per run so two
    arms can be proven to differ only where intended."""
    return hashlib.sha256(_effective_prompt_text(cfg).encode()).hexdigest()[:12]


def fragment_names(cfg: dict) -> list[str]:
    """Which clauses this arm's prompt actually carries — recorded per run so two arms
    can be PROVEN to differ only where intended.

    Kept under the old name because run_arm.py records it as `prompt_fragments` and
    agent.py prints it in the [SESSION] header. What it lists changed on 2026-08-09:
    appended fragment files became resolved {{marker}} clauses.
    """
    return [n for n, (pred, _stem) in _MARKERS.items() if pred(cfg)]