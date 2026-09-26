# skills/transforms/ -- NOT a skill tier

These files are inputs to the SKILL MAKER (`skillmaker.py`, discovery mode with
`evolve: true`). They are never listed by `get_skill()` and the analysis agent never sees
them. `tools._skill_tiers()` knows only `base` and `additional`, and nothing globs this
folder into a menu; keep it that way.

Each file states what changes and what does not when an analysis moves from one setting
to another, so that a rule copied from a primitive skill can be carried across, changed or
dropped deliberately rather than by guesswork. First line is the title, second line is
`applies_when:` (the one-line summary the skill maker's menu shows), then four fixed
sections: what changes; rules that carry over unchanged; rules that change, and how; rules
that are new; checks to add.

Drafted by Claude on 2026-09-15 for the user's correction. Design: `code/analysis/skill-evolve/PLAN.md`.
