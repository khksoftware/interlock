# Interlock

<img src="assets/exec-e4b02415-3d9e-4224-8595-55315a28175d.png" align="left" width="230"
     alt="A hard-hatted figure standing behind a lowered black-and-yellow boom barrier."
     hspace="20" vspace="6">

**A constraint that cannot be forgotten, because the action will not proceed.**

An interlock, in engineering, is a device that makes an action *impossible* unless a
condition holds: the press that will not cycle with the guard open, the chamber door that
will not release under pressure. Not a warning. Not a checklist. Not a reminder. The
action does not proceed.

This package is that idea applied to software development with AI coding agents, at the
three boundaries such a workflow actually has:

- **`interlock.git`** — refusals that fire at the moment a **git action** is attempted:
  `pre-commit`, `commit-msg`, `reference-transaction`.
- **`interlock.turn`** — refusals and reminders that fire at the moment an **agent turn**
  is about to end or begin: a supervisor/worker dispatch loop's own hook events.
- **`interlock.guard`** — a refusal that fires **before a command executes**: a
  high-confidence, long or I/O-heavy shape blocked before it runs, until an explicit,
  disclosed, one-shot approval clears it.

Three hosts, one idea, and **one install-and-arm discipline shared between them**. That
single discipline is the point of this package, not merely its packaging.

<br clear="left">

## The problem this exists to solve

A rule can be written down correctly, delivered to whoever is about to act, and read by
them in full — and still not hold, because the moment it needed to bind was minutes or
hours after the moment it was read. A standing instruction lives in a brief, an onboarding
doc, a system prompt, or an agent's own working memory of a policy; the action it governs
happens later, under time pressure, in the middle of solving a different problem. By then
the rule is not "unknown," it is simply not *retrieved* — nothing at the point of the
action asks whether it applies.

This is a measured failure mode, not a hypothetical one, and it recurs identically at
every boundary this package targets. On the git side: a correct, present, well-written rule
("never embed an absolute path," "never `git stash`," "no vendor attribution on a commit")
was violated anyway, repeatedly, because nothing stood between the intention and the
action to ask "does a rule apply here?" On the agent-turn side: a standing obligation
("every message opens with the right role label," "keep dispatching while there is ready
work," "the board should match what was actually dispatched") was adopted, correctly
stated, and still lapsed across a long session — because an announced action reads as a
taken one, a delivered report reads like the end of a turn, and a resumption point is
exactly where a self-applied habit is least likely to survive, because attention has just
been pulled elsewhere. Before a command even runs: a standing cost-proportionality
practice ("prefer the cheaper alternative," "run the change-triggered closure, not the
full suite") was known, stated, and still overridden under time pressure, in the middle of
solving a different problem — the identical gap, one boundary earlier.

**The only mechanism that reliably closes this gap is one that does not depend on the
actor remembering anything: a check that runs automatically at the moment the action is
about to happen, and refuses it — or, where refusing is the wrong bias, surfaces an
unmissable reminder — regardless of who is acting or whether they meant to.** That is an
interlock. `interlock.git` is that mechanism at the git-action boundary; `interlock.turn`
is that mechanism at the agent-turn boundary; `interlock.guard` is that mechanism one step
earlier still, before a command executes at all — the same idea, aimed at the three
places an AI-assisted development loop needs it.

## Independent adoption — this is not an all-or-nothing framework

**Taking one host does not drag in the other.** That holds in the code, not only in the
prose below, and it is proven rather than asserted by `tests/test_module_independence.py`,
which physically deletes one host's subpackage directory from a copy of this source tree
and runs the other host's real checks, as real subprocesses, against what remains.

### Path 1 — git-action gates only, no agents involved at all

**A completely ordinary repository with no AI agent, no delegation, and no harness in the
loop benefits from `interlock.git` exactly as much as one that also uses `interlock.turn`.**
This is a first-class, common case, not a subset of some larger requirement:

```bash
pip install interlock          # or: PYTHONPATH=/path/to/interlock/src
cd your-project

interlock install git.protected-paths
interlock install git.absolute-local-path
interlock install git.synthetic-git-identity
interlock install git.commit-message-pattern
# git.stash-invocation is a separate, deliberate decision -- see docs/INTEGRATION.md.
```

Three of those four share the `pre-commit` hook name, and git dispatches exactly one file
per hook name -- `install` composes them onto it automatically, in whatever order you run
them, rather than requiring you to know that ahead of time or refusing on the second one.
`interlock status` afterward reports every one of them as installed and armed, not as a
foreign hook occupying the name; see `docs/INTEGRATION.md` §5 for exactly what changes
when the pre-existing occupant of a hook name is something this package did NOT write.

Nothing above requires `interlock.turn` to be configured, imported, or even present.
`interlock.git` never imports it, and the five gates it ships read only git's own state
(the staged index, the proposed commit message, a ref-transaction batch) plus an optional
`interlock.json` config file at your repository root.

### Path 2 — agent-turn hooks only, no git-side gates

**An estate that wants the turn-boundary guardrails without touching its git hooks at all
gets exactly that, and nothing more.** `interlock.turn` never imports `interlock.git`, and
none of its seven hooks depend on any git gate being installed, armed, or present:

```bash
pip install interlock
# Wire whichever hooks you want into your harness's own hook configuration --
# see docs/INTEGRATION.md for the exact settings.json shape Claude Code expects:
#   Stop -> python -m interlock.turn.role_label
#   Stop -> python -m interlock.turn.idle_roster
#   ...

interlock arm turn.role-label
interlock arm turn.idle-roster
```

### Path 3 — the pre-execution guard only, nothing else required

**An estate that wants only the before-a-command-runs check gets exactly that.**
`interlock.guard` never imports `interlock.git` or `interlock.turn`, and its one hook
depends on neither:

```bash
pip install interlock
# Wire it into your harness's own pre-tool-use hook configuration --
# see docs/INTEGRATION.md for the exact settings.json shape Claude Code expects:
#   PreToolUse -> python -m interlock.guard.execution_guard

interlock arm guard.execution-guard
```

### Path 4 — any combination

Installing more than one host is exactly the paths above performed in the same
repository, in any order. Nothing about combining them changes what any one requires on
its own — there is no combined configuration format, no shared prerequisite state, and no
"framework mode" that activates once more than one is present. What they share is
described below: one marker mechanism, one configuration *file* for the hosts that use
one (each reads only its own section of it), and one CLI surface for managing all of
them.

### What this package does NOT require you to adopt

**These are enforcement mechanisms, not a methodology.** Taking either host does not
commit you to a delegation lifecycle, a particular session-record format, a two-hat
supervisor/worker convention, or any surrounding process framework beyond the literal,
narrow thing each check verifies. Where a specific hook genuinely needs a piece of
external state to do its job — `interlock.turn.idle_roster` needs *some* JSON file
describing a roster and a queue if you want it to do anything at all — that requirement
is named explicitly, in that hook's own module docstring and in `docs/USAGE.md`, rather
than implied to be part of a larger required system. A repository can arm
`interlock.turn.role_label` alone and never touch the session-record schema at all; that
hook has no dependency on it.

## The one install-and-arm discipline

```
interlock install  git.protected-paths
interlock arm      git.protected-paths
interlock status
```

Every gate and hook in this distribution shares one rule: **installing (wiring something
in) and arming (this worktree actually enforcing it) are two separate, disclosed acts, and
installing never silently imposes anything on a worktree or a session that did not ask for
it.**

- **`interlock.git`.** Git hooks resolve through the repository's COMMON git directory
  (`git rev-parse --git-common-dir`), which every linked worktree of a checkout shares —
  installing a hook from one worktree makes it fire in every other worktree of that same
  repository. So installation is split: a tiny, fixed, byte-frozen shell shim is written
  ONCE into the shared hooks directory and is a no-op by default; each worktree then
  independently arms itself by writing a marker file into ITS OWN `git rev-parse
  --git-dir`, which resolves separately per worktree even though the shim does not. An
  unarmed worktree's shim reads no marker, finds none, and exits 0 having loaded nothing.

- **`interlock.turn`.** Every hook checks its OWN per-worktree marker before doing
  anything else — stored in the exact same `git rev-parse --git-dir` location a git
  gate's marker lives in, written and read by the literal same function. Unarmed means a
  silent no-op: no block, no reminder, nothing printed, exactly mirroring an unarmed git
  shim. Wiring a hook into a harness therefore does not, on its own, make it enforce
  anything in any worktree.

- **Where the two structurally cannot be identical, stated plainly rather than forced.**
  A git hook has a shim to install: a fixed file at a fixed, shared, single-file-per-event
  location git itself dispatches to. A turn-boundary hook has no such thing — an AI coding
  harness invokes whatever command its own hook configuration names, directly, with no
  git-style indirection layer in between. So `interlock.turn`'s WIRING (which command
  appears in `settings.json`) remains what it always was: a manual, disclosed edit you make
  yourself, documented in `docs/INTEGRATION.md`. `interlock install turn.<hook>` therefore
  arms the marker **and prints the exact `settings.json` entry to add**, rather than
  writing that file itself — advisory, never mutating, and it says so. There is no
  "install once, shared" step on this host, because there is no shared indirection file
  to install into.

`interlock status` reports both facts — installed/wired, and armed — for every gate and
hook this distribution ships, or for one given by id. Conflating "installed" with
"therefore enforcing" is exactly the invisible gap arming exists to close; a status
command that only reported one of the two facts would reintroduce it in a different form.
"Installed" recognizes a gate whether it is the sole occupant of its hook name, composed
onto that hook name alongside other interlock gates by `install` itself, or composed onto
it by hand per `docs/INTEGRATION.md` §5 — a correctly-enforcing gate is never reported as
a foreign hook merely because more than one gate shares its hook name.

### Naming a gate

An identifier has the shape `<host>.<name>` for the CLI (`git.protected-paths`,
`turn.idle-roster`, `guard.execution-guard`), corresponding one-to-one with the check's
own dotted Python module path (`interlock.git.protected_paths`,
`interlock.turn.idle_roster`, `interlock.guard.execution_guard`).

## What ships

### `interlock.git` — five gates

| Gate | Hook | What it refuses |
| --- | --- | --- |
| `protected_paths` | `pre-commit` | A commit whose changed-path set touches a path you have registered as off-limits (exact path or prefix), edit or delete alike. |
| `absolute_local_path` | `pre-commit` | A commit whose staged content embeds an absolute local filesystem path (a Windows drive path, a UNC path, a POSIX home directory), with an adopter-owned exemption registry for genuine citations. |
| `stash_invocation` | `reference-transaction` | A `git stash` invocation, at the one hook that actually observes it (`pre-commit`/`commit-msg` see nothing — stash never runs `git commit`). |
| `synthetic_git_identity` | `pre-commit` | A commit made under a `user.email` left set to an IANA-reserved documentation domain (`example.com`/`.org`/`.net`/`.invalid`) or `localhost` — the residue of proving something under a throwaway identity and forgetting to unset it. |
| `commit_message_pattern` | `commit-msg` | A commit message whose trailer (default: `Co-Authored-By`) matches a forbidden pattern (default preset: known AI vendor/model/harness identities) — configurable to any trailer key and any pattern set. |

Every gate shares one installer, one arming discipline, and one hook-shim renderer
(`interlock.git.hookkit`), and reads git's own plumbing through one shared, tested module
(`interlock.plumbing`).

### `interlock.turn` — seven hooks

| Hook | Fires on | What it does |
|---|---|---|
| `subagent_start` | a worker is dispatched | records a best-effort entry in a user-level outstanding-agent registry |
| `subagent_stop` | a worker returns | removes that entry |
| `user_prompt_submit` | a new turn begins | reminds (never enforces) the role-label rule and an outstanding-agent live-probe, escalated at resumption boundaries |
| `role_label` | a turn is ending | refuses if any assistant message of the ending turn lacked exactly one valid role label, or if the turn's first message — the one answering the operator — used the worker label instead of the supervisor's |
| `announced_action` | a turn is ending | refuses if the turn's final message announces an imminent action with no tool call taking it |
| `idle_roster` | a turn is ending | refuses if the roster is verified-empty while a sequenced, unblocked, non-exempt row sits `queued` |
| `roster_reconciliation` | a turn is ending | refuses if this session's own transcript shows a live, un-notified dispatch missing from the hand-written roster; reports (never refuses on) the reverse mismatch, which carries real cross-session ambiguity |

Every hook is a small, independent, plain Python module reading a JSON payload on stdin
and printing a JSON verdict on stdout. `interlock.turn.session_record` and
`interlock.turn.outstanding` hold the logic two or more hooks share, so a shared invariant
is a single tested implementation rather than independently drifting copies.

### `interlock.guard` — one hook

| Hook | Fires on | What it does |
|---|---|---|
| `execution_guard` | before a command executes | refuses a command whose text matches a small, fixed set of high-confidence expensive shapes (an additional git worktree, a full-tree or full-test-suite scan, a whole-file database copy, recursive hashing), until an explicit, expiring, one-shot approval bound to the command's exact SHA-256 clears it |

A heredoc's or here-string's payload embedded in the same command string is stripped
before classification **only when** a real closing terminator is confirmed, the body's
opening line does not feed it to a recognized shell/PowerShell interpreter, and the
heredoc's own `<<` is confirmed to sit outside any quoted text (tracked across lines, and
aware of a backslash-escaped quote character) — so content that merely MENTIONS an
expensive shape is not confused with a command that will actually run one, while a heredoc
body a shell is actually about to run, one whose terminator is never confirmed, or an
ordinary quoted string that happens to contain `<<` and a later coincidentally-matching bare
word, is left visible rather than silently discarded. See the module's own docstring and
"Limits" below for the residue classes this does not, and cannot fully, close: a command
string is all this hook ever sees, so content written through any other kind of tool call is
invisible to it; the set of interpreter names recognized on a heredoc's opening line is
finite, so a body fed to an interpreter under an unrecognized name is treated as inert and
stripped anyway; and the quoted-text check itself is a cheap, character-level approximation
of shell quoting, not a full grammar parser, so a construct that reopens or changes quoting
context through shell expansion is not modeled.

## What is shared, and what is intentionally separate

Implemented once and used by more than one host:

1. **The install-and-arm marker mechanism** (`interlock.arming`) — one function set, used
   by `interlock.git.hookkit` for git gates, `interlock.turn.arming` for turn hooks, and
   `interlock.guard.arming` for the pre-execution guard alike. Proven, not just claimed:
   `tests/test_arming.py::TestGitAndTurnMarkersCoexist` arms one of each kind in the same
   worktree through the identical function and shows neither collides with the other.
2. **Git plumbing and repository-root discovery** (`interlock.plumbing`) — every host
   resolves "where is this repository" through the same function, which decodes git's
   output as UTF-8 explicitly rather than relying on the platform's default codepage.
   One implementation means no host can disagree about what the repository root is, or
   about how a non-ASCII path decodes.
3. **Configuration file and discovery** (`interlock.config`) — one JSON file,
   `interlock.json`, at the repository root, with one section per gate or hook that wants
   file-based configuration. `interlock.git`'s gates each read their own section.
   `interlock.turn` is primarily environment-variable-configured — see below for why that
   asymmetry is deliberate — but its one adopter-owned *structured* setting
   (`session_boundary_rows`, an id-to-reason exemption map) also falls back to this same
   shared file's `"turn"` section, so an adopter already using `interlock.json` for the
   git side gets it without a second file to maintain. `interlock.guard` is entirely
   environment-variable-configured, for the same reason `interlock.turn` is (see below),
   and has no section of this file at all -- there is no structured setting of its own
   worth a second file for yet.
4. **One CLI** (`interlock install|arm|disarm|status`) covering every gate and hook on
   every host.
5. **One versioning scheme, one `CHANGELOG.md`, one `RELEASE_PROCESS.md`.**
6. **Deployed-copy pinning** (`interlock.deployment_pinning`, `interlock pin-check <id>
   --deployed-path <path>`) — for an adopter whose deployment convention copies a turn or
   guard hook's file into a per-user hooks directory rather than invoking the installed
   package directly, one CLI verb verifies that copy against its own tracked source, on
   any host, by id. See `docs/INTEGRATION.md`'s "Deployed-copy pinning" section. Not an
   armed, automatically-running check — a callable and a CLI verb you run on your own
   cadence.

Deliberately separate, because forcing symmetry would be dishonest:

- **`interlock.turn`'s and `interlock.guard`'s configuration is environment-variable-primary.**
  A turn hook or the pre-execution guard is invoked by the harness as a subprocess; the one
  thing every harness reliably lets an adopter control at that point is the subprocess's own
  environment, not a bespoke config-file convention this package would have to teach every
  harness about. See `interlock.turn.config`'s and `interlock.guard.config`'s own module
  docstrings.
- **Neither `interlock.turn` nor `interlock.guard` has a shim to install**, because there is
  no shared, single-file-per-event indirection layer on either side to install into — see
  "The one install-and-arm discipline" above.
- **Fail-closed versus fail-open remain different, on purpose, per host.** See "Design
  principles" below.

## Limits — what this cannot catch

A framework that implies more coverage than it has is worse than one that claims less and
is right. Some of what you might want refused at a boundary is not reachable from any
boundary, and this section says which, so you do not discover it by being surprised.

Each hook and gate documents the specific shape of failure it closes in its own module
docstring. **Read that docstring before relying on one for something its shape does not
cover** — the name alone will mislead you.

The honest way to size this for your own project is to enumerate your own real incidents
and classify each one: armed and reliable, solved but not armed, reachable only from a
different boundary, or permanently unreachable. **"Solved" and "armed" are different
facts, and a built-but-unarmed gate protects nothing.**

### Residue classes — permanent, not merely unimplemented, stated per host

**`interlock.git`'s two permanent blind spots:**

- **No git event at all.** Some standing constraints govern a decision to do *nothing* —
  "you finished a wave of work and there is more queued; keep going" is not a commit, a
  stash, or any other git action, so there is no hook to attach a refusal to. (This is
  exactly the gap `interlock.turn.idle_roster` and `announced_action` close, at the
  boundary where an omission or an unfulfilled announcement IS observable — a turn ending,
  not a git action. Adopting `interlock.turn` alongside `interlock.git` narrows this
  residue; it does not eliminate the git host's own inability to see it.)
- **A git event with no role or identity signal.** A commit, a stash, or a ref update
  carries no reliable signal distinguishing *who* — which person, which role, which
  process — performed it. `protected_paths` can refuse "path P moved," which is
  observable; it cannot refuse "path P moved and it was not role X that moved it,"
  because "which role acted" is not a fact any git hook is ever handed.

**`interlock.turn`'s two permanent blind spots:**

- **No boundary event to attach to, for the REASONING behind an action.** A turn-boundary
  hook observes a turn ending, a prompt being submitted, or a sub-agent starting or
  stopping — it cannot observe the reasoning that led to those moments. It can only ever
  refuse an *action* (or the absence of one at a specific, observable boundary); it has no
  purchase on the quality of the thinking behind it.
- **Surface pattern versus semantic truth.** Every hook here is a pattern, schema, or
  set-membership check over transcript text or a small JSON record. `role_label` proves a
  label was present and well-formed; it cannot prove the label was the *right* hat for
  what the message actually did. No version of this package closes this — it is the
  boundary between what a script can read off a transcript and what only genuine judgement
  can verify.

**`interlock.guard`'s three permanent blind spots, the first still the sharpest across the
whole package:**

- **Channel-dependent coverage.** This hook reads a command STRING handed to it through a
  recognized shell-tool call. Content written through any other kind of tool call — a
  structured file-write, an edit, a patch application — produces no command string for
  this hook to read at all, so it is never even invoked with anything to scan for that
  channel. **A clean run, or no invocation at all, is not evidence that content written
  some other way was checked for cost.** Closing this would mean moving the check off the
  command string entirely, onto some effect a harness exposes uniformly across every tool
  — a different and substantially larger mechanism than this one, of uncertain
  reachability on any given harness, and not something this package's current design
  attempts.
- **Interpreter-name coverage is a finite, named list.** A heredoc's or here-string's body
  is treated as inert data — and stripped before classification — unless its opening line
  names or pipes into one of a fixed set of recognized shell/PowerShell interpreters. An
  interpreter invoked under a name not on that list (an obscure shell, an alias, a wrapper
  script) is not recognized, so a body it is actually about to run is stripped anyway, the
  same failure this hook exists to prevent. The list is disclosed in the module's own
  docstring, not silently assumed complete, and growing it narrows this residue without
  ever provably exhausting it: an adopter can always invoke something under a name this
  package has not seen.
- **Quote-tracking is a character-level approximation of shell quoting, not a shell-grammar
  parser.** Deciding whether a `<<` sits inside quoted text is done by counting quote
  characters (across lines, and aware of a backslash-escaped quote), the same cheap, local
  approach every rule in this hook uses — not by parsing the command the way a real shell
  does. A construct that reopens or changes quoting context through shell expansion (command
  substitution, ANSI-C `$'...'` quoting, backtick substitution) is not modeled, and is not
  claimed to be. Biased the same direction as the rest of this hook: what this cannot
  correctly resolve is treated as "still inside a quote," so the failure mode is a body left
  visible to the classifier, never a real command silently discarded.

Every class above, on every host, is permanent, not merely unimplemented. Nothing proposed
for a future version of this package closes any of them, and a roadmap that claimed
otherwise would be the overstatement this section exists to prevent.

### What was deliberately left out

An eighth turn hook is not included: a `PreToolUse` check that refuses a dispatch when a
canonical worker-definition file and the copy the harness actually reads have drifted. It
depends on a multi-repository, multi-directory skill-and-definition sync tool and that
tool's exact report schema, so shipping it faithfully means shipping that whole sync tool
as a first-class feature of its own, not adapting a small hook. A future release may
add a generic version; until then, adopting this package means the freshness of whatever
standing worker-definition file you use is your own responsibility to keep in sync with
wherever your harness reads it from.

Session-continuity *skills* — procedural documents a model reads when invoked, for things
like preparing a session for a context compaction and resuming cleanly afterward — are
also not included. Such procedures are only useful when written against a specific
session-record format, governance layer and role model, and a version general enough to
ship here would be too vague to follow. This package stays enforcement mechanisms rather
than procedure.

### Auditing history for undisclosed violations: a structural blind spot, published as a rule, not a count

A natural adopter question, on the git side, is retrospective: "before I armed this, did
anyone violate the rule and leave no trace?" Any such audit walks git's commit graph —
commit messages (`git log --grep`), commit diff content (`git log -G` / `git show --cc`),
and unreachable-but-undeleted commits (`git fsck --unreachable`). **All three of those
methods share one blind spot: they only ever visit commits.** A ref can point directly at
a tree, a blob, or an annotated tag instead of a commit — bypassing the commit graph
entirely — and content living there is invisible to every one of the three methods.

This is not a hypothetical edge case; it is present, right now, in ordinary
repositories — a CI system's own checkpoint refs, a code-review tool's own annotation
refs, and `refs/stash` itself. The honest response is to stop publishing a count and
publish the **predicate** instead — a number in a document goes stale the instant anyone
writes a new ref; a predicate does not:

```bash
# Every ref whose target is not a commit, resolved fresh, right now, in this repository:
git for-each-ref --format='%(objecttype) %(refname)' | awk '$1 != "commit"'
```

Run that before trusting any historical "we swept the whole history and found nothing"
claim — including this package's own, if you ever run a similar audit against a
repository it protects.

## Design principles, in one place

- **Fail closed on `interlock.git`; fail OPEN on `interlock.turn` — deliberately, not by
  accident, and this is the sharpest asymmetry between those two hosts.** If a git gate
  cannot determine whether an action is safe, it refuses — an unverifiable action is not a
  verified one (`interlock.errors.GateError`). If a turn-boundary hook cannot read its
  transcript, its session record, or its payload, it does nothing and blocks nothing. This
  is not an inconsistency to fix; it reflects a real difference in what a false positive
  costs on each side. A blocked commit costs a `--no-verify` and a disclosed note. A
  turn-boundary hook that wedges every turn on any I/O hiccup gets disabled by its own
  operator within a day, and a disabled hook protects nothing at all.
- **`interlock.guard` sits between the two, by design, not as an unresolved compromise.**
  It fails OPEN on anything it cannot classify or was never handed to scan at all — the
  same bias as `interlock.turn`, for the same reason: a guard that wedges every command it
  cannot parse gets disabled by its own operator. But once a command's text DOES match one
  of its fixed, high-confidence expensive shapes, it refuses exactly as unconditionally as
  a git gate does, until an explicit, disclosed approval clears it. Ambiguous: open. Matched:
  closed. Never the other way around.
- **The shim holds no logic** (git side). Everything a gate could get wrong lives in a
  tracked, tested Python module; the installed hook file is a small, fixed, byte-frozen
  shell script that only `exec`s that module.
- **Arm per worktree, wire once — on every host, per "The one install-and-arm
  discipline" above.**
- **Bypassable, and that is stated, not hidden.** `git commit --no-verify`, repointing
  `core.hooksPath`, deleting a worktree's own arming marker, or removing a hook entry from
  `settings.json` all skip these checks. Every module's own documentation says so. A
  hook-based check raises the cost of a violation reaching the repository or the
  transcript unnoticed; it does not make one impossible.
- **Scoped to what the moment actually carries.** Every git predicate reads only the
  content of the action in front of it — never a repository-wide walk. Every turn hook
  reads only the transcript, payload, or record in front of it at the boundary it fires
  on — never a query to the harness's own live process state (see
  `roster_reconciliation`'s own docstring for why a live liveness probe is deliberately
  never attempted there). The pre-execution guard reads only the one command string it was
  handed — never a broader search of what else is running or what else was recently done.
- **Configuration lives in as few places as each host's own constraints allow** — one
  shared file for anything file-based (`interlock.config`), environment variables where
  that is genuinely the only mechanism a harness reliably exposes
  (`interlock.turn.config`, `interlock.guard.config`). A hook or gate module with a
  project-specific literal typed into its own logic is a bug in this package, not a
  feature of an adopter's fork.

## Where to go next

- **`docs/INTEGRATION.md`** — installing this into a real project: adoption paths (git
  alone, turn alone, the pre-execution guard alone, or any combination), hook wiring,
  arming markers, and what to do if a `pre-commit` hook or a `settings.json` entry already
  exists.
- **`docs/USAGE.md`** — every configuration knob, the session-record schema, and how to
  author a new gate or hook of any class.
- **`CHANGELOG.md`** / **`RELEASE_PROCESS.md`** — versioning and how a release is cut.
- **`tests/`** — the full suite this README's claims are checked against, including
  `test_module_independence.py`'s physical proof of independent adoption; run it yourself
  (`python -m pytest tests` from this directory) before trusting anything above.

## Contact

Questions, bug reports and adoption problems: **khksoftware@gmail.com**.

## License

Apache-2.0. See the `LICENSE` file, and the `SPDX-License-Identifier` header on every
source file in this distribution.
