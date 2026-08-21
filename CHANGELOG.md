# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: this project
follows [Semantic Versioning](https://semver.org/) — see `RELEASE_PROCESS.md` for exactly
what that commits to for this package, since "semver" alone under-specifies what counts as
breaking for a package whose product is partly *behavioural* (a gate or hook refusing, or
reminding about, something it did not before) rather than only a Python API.

## [Unreleased]

Three fixes:

- **Fixed: the join pass refused ordinary prose.** Fusing on boundary characters alone
  joined a line ending in a bare drive colon to a following line opening with a forward
  slash — `drive D:` above `/dev/null is empty` became `D:/dev/null` and was refused,
  though neither line embeds a local path. That one shape is now excluded, and a genuine
  wrapped Windows path is unaffected because the drive form continues with a backslash.
  Three regression tests pin the prose cases. A gate that refuses good commits gets
  bypassed as a habit, which costs more than the narrow evasion the join pass closes.
- **Fixed: `absolute_local_path` was defeated by an ordinary line break.** Its predicate
  scanned line by line only, so a path wrapped across two lines (a copy-pasted log, a
  hard-wrapped table cell) passed with no signal at all. It now also re-scans each
  adjacent line pair whose join point itself looks like a continuation of a path (a
  separator or a drive colon), reporting a spanning match under the first line's number
  and never double-reporting content already caught per line. This is a deliberately
  narrow, join-aware repair, not a blanket whole-file join (which would itself produce
  spurious refusals) — a break strictly inside a path segment, or a path wrapped across
  three or more lines, can still evade; see the module's own docstring for the full,
  honest account of what remains.
- **Fixed: more than one `pre-commit` gate sharing that hook name was not a first-class
  path.** `README.md`'s own "Path 1" quickstart lists four `interlock install` commands
  back to back; three of them share `pre-commit`, and the second and third used to refuse
  outright with no warning, from a fresh repository, every time. `install` now composes
  automatically onto a hook name already occupied by another of this package's own gates
  (never onto a genuinely foreign hook, which is still refused exactly as before) — see
  `interlock.git.hookkit`'s own docstring for the design. `docs/INTEGRATION.md` §5 is
  updated to describe this as the default, keeping the hand-composed alternative it
  already documented as a still-supported escape hatch.
- **Fixed: `interlock status` reported a correctly-enforcing, composed `pre-commit` hook
  as a "FOREIGN hook."** Whether composed automatically by `install` or by hand per
  `docs/INTEGRATION.md` §5, `status` now recognizes it as installed rather than
  conflating "not byte-identical to one gate's own solo shim" with "not managed by this
  package at all."

## [0.1.0] — initial unified release

**Interlock replaces two standalone exports, `action-boundary-gates` (the git-action
host) and `agent-dispatch-guardrails` (the agent-turn host), which are deleted from this
repository in the same change that adds this package.** They were built and released
separately, which was a mistake corrected here: they are one framework with two host
modules, not two frameworks. See `README.md` for the unifying idea and exactly what
genuinely became shared versus what stayed deliberately separate.

**This is a breaking rename, not a drop-in replacement, and every one of the following
is a deliberate, disclosed change from the two predecessor packages:**

- Distribution and import package renamed to `interlock`. Host subpackages are
  `interlock.git` (was `action_boundary_gates`) and `interlock.turn` (was
  `agent_dispatch_guardrails`).
- Git-gate marker names renamed from `action-boundary-<gate>` to
  `interlock-git-<gate>` — a worktree armed under a predecessor package's marker name is
  silently unarmed under this package and must be re-armed.
- The shared adopter-owned config file renamed from `action-boundary-gates.json` to
  `interlock.json`.
- Turn-host hook modules flattened out of a `hooks/` subpackage and renamed:
  `stop_role_label` → `interlock.turn.role_label`, `stop_announced_action` →
  `interlock.turn.announced_action`, `stop_idle_roster` → `interlock.turn.idle_roster`,
  `stop_register_roster_reconciliation` → `interlock.turn.roster_reconciliation`.
  `subagent_start`, `subagent_stop`, and `user_prompt_submit` keep their names, at the new
  path.
- Turn-host environment variable prefix renamed from `ADG_` to `INTERLOCK_` (e.g.
  `ADG_SUPERVISOR_LABEL` → `INTERLOCK_SUPERVISOR_LABEL`) across every setting in
  `interlock.turn.config`.
- The best-effort outstanding-agent bookkeeping module renamed from `registry.py` to
  `interlock.turn.outstanding` — the name `interlock.registry` now belongs to the
  unified CLI's own id table (see below), a genuinely different thing.

**What is new, not merely renamed:**

- **`interlock.turn` gained the install-and-arm discipline it never had.** Every one of
  the seven turn-boundary hooks now checks its own per-worktree marker
  (`interlock.turn.arming`, built on the identical shared primitive
  `interlock.arming` a git gate's own marker uses) before doing anything at all. Before
  this release, a wired-in turn hook ran unconditionally, in every worktree
  `settings.json` reached, with no way to arm one worktree and not another. This is a
  real behavioural change: an adopter upgrading from `agent-dispatch-guardrails` must run
  `interlock arm turn.<hook>` for every hook they want active, or those hooks will run
  silently as no-ops.
- **One unified `interlock` CLI** (`install` / `arm` / `disarm` / `status`), replacing
  five separate `--install`-flagged CLI modules on the git side and no install/arm/status
  surface at all on the turn side.
- **One shared configuration and discovery mechanism** (`interlock.config`,
  `interlock.plumbing`) used by both hosts. Fixed one latent, if minor, defect in the
  process: `interlock.turn`'s predecessor package resolved its own repository root with
  `subprocess.run(..., text=True)`, which decodes with the platform's default codepage
  rather than UTF-8 explicitly; the shared `interlock.plumbing.repository_root` does not.
- **`interlock.turn`'s one structured, file-based setting**
  (`session_boundary_rows`) can now be read from the shared `interlock.json`'s `"turn"`
  section as a fallback beneath its own environment-variable override, rather than
  requiring a second, separately-maintained file.
- `tests/test_module_independence.py` — a new suite that physically proves each host
  works with the other's subpackage directory deleted from a copy of the source tree,
  including a real installed git-gate commit refusal and a real armed/unarmed turn-hook
  subprocess run.

**Carried forward unchanged in substance:** all five git-action gates
(`protected_paths`, `absolute_local_path`, `stash_invocation`, `synthetic_git_identity`,
`commit_message_pattern`) and all seven turn-boundary hooks, their predicates, their
documented incident shapes, their disclosed residue classes, and the full test suite of
both predecessor packages (72 + 102 = 174 tests), ported and passing, plus the additions
above.
