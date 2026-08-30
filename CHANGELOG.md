# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: this project
follows [Semantic Versioning](https://semver.org/) — see `RELEASE_PROCESS.md` for exactly
what that commits to for this package, since "semver" alone under-specifies what counts as
breaking for a package whose product is partly *behavioural* (a gate or hook refusing, or
reminding about, something it did not before) rather than only a Python API.

## [Unreleased]

## [1.0.0] — 2026-08-30

**Breaking: bare blocker prose no longer suppresses `turn.announced-action` by itself.**
The hook now corroborates `once`, `await`, `waiting on/for`, `waits on`, and `blocked on`
against the exact selected platform in the configured session record. The first blocker
object must fully match the configured id pattern and every id-shaped token in that
immediate clause must name a row whose portable status is exactly `queued`, `running`,
or `blocked`. Closed, fabricated, malformed, unknown, wrong-platform, or uncorroborated
ids retain the announcement and therefore refuse the ending turn. Adopters upgrading
from 0.2.0 should set `INTERLOCK_SESSION_PLATFORM` (default `default`) and expose those
portable row statuses in their session record; without a readable unique selected node,
the hook remains armed and conservative.

Role labels now accept either the configured plain spelling (`[Supervisor]`, `[Worker]`)
or that exact spelling wrapped in two Markdown bold markers. Both normalize to the same
identity for strict every-message, blended-label, and first-message channel enforcement;
other decoration remains invalid.

## [0.2.0] — 2026-08-27

**Added: `interlock.guard`, a third host — refusals that fire before a command executes.**
A single hook, `execution_guard` (`guard.execution-guard`), refuses a command whose text
matches a small, fixed set of high-confidence expensive shapes (an additional git
worktree, a full-tree or full-test-suite scan, a whole-file database copy, recursive
hashing) until an explicit, disclosed, one-shot approval bound to the command's exact
SHA-256 clears it. Built with the same install-and-arm discipline `interlock.turn`
established (`interlock.guard.arming`, sharing the underlying `interlock.arming` marker
primitive) and the same environment-variable-primary configuration
(`interlock.guard.config`). A heredoc's or here-string's payload embedded in the same
command string is stripped before classification only when a real closing terminator is
confirmed, the opening line does not feed the body to a recognized shell/PowerShell
interpreter, and the heredoc's own `<<` is confirmed to sit outside any quoted text — tracked
across lines, since a quoted string is not obliged to close on the line it opened, and aware
of a backslash-escaped quote character, since that does not close the string it sits inside
either — so content that merely mentions an expensive shape is not confused with a command
that actually runs one, while a body a shell is genuinely about to run, a heredoc with no
confirmed terminator, or an ordinary quoted string (on one line or spanning several) that
happens to contain `<<` and a later coincidentally-matching bare word are all left visible
rather than silently discarded. Three residues remain and all are documented as permanent
residue classes in `README.md`'s Limits section, not silently implied away: the
channel-dependent coverage this hook cannot close at all (nothing scans content written
through a non-shell tool call); a finite, named list of recognized shell/PowerShell
interpreters, so a body fed to an interpreter under an unrecognized name is stripped as if it
were inert even when it will actually execute; and the quoted-text check itself is a
character-level approximation of shell quoting rather than a full grammar parser, so a
construct that reopens or changes quoting context through shell expansion is not modeled.
`interlock.registry`/`interlock.cli` extended to cover the new host
identically to the other two; `tests/test_module_independence.py` extended with a third
class proving `interlock.guard` imports neither other host and works with both physically
removed.

**Added: `interlock.deployment_pinning` and `interlock pin-check`.** `interlock.git`'s
deployed shim holds no logic and this package already verifies it against the rendered
shim; `interlock.turn` and `interlock.guard` had no equivalent for the case where an
adopter deploys one of their hooks as a standalone copied file rather than invoking the
installed package directly — that copy had no built-in relationship to the package's own
source once copied, and nothing detected drift. `interlock pin-check <id> --deployed-path
<path>` closes this uniformly across every host: for a turn or guard id, against that
hook's own installed module source resolved live via `importlib`; for a git id, against
the exact shim text this package would render, the same basis `interlock status` already
uses internally. A callable and a CLI verb, not an armed automatic check — nothing wires
it into any hook event on an adopter's behalf.

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
