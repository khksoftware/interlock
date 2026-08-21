# Interlock

**A constraint that cannot be forgotten, because the action will not proceed.**

An interlock, in engineering, is a device that makes an action *impossible* unless a
condition holds: the press that will not cycle with the guard open, the chamber door that
will not release under pressure. Not a warning. Not a checklist. Not a reminder. The
action does not proceed.

This package is that idea applied to software development with AI coding agents, at the
two boundaries such a workflow actually has:

- **`interlock.git`** — refusals that fire at the moment a **git action** is attempted:
  `pre-commit`, `commit-msg`, `reference-transaction`.
- **`interlock.turn`** — refusals and reminders that fire at the moment an **agent turn**
  is about to end or begin: a supervisor/worker dispatch loop's own hook events.

Two hosts, one idea, and — this is the part that used to not be true — **one
install-and-arm discipline shared between them**. Read on for why that unification is the
actual point of this package, not merely its packaging.

## The problem this exists to solve

A rule can be written down correctly, delivered to whoever is about to act, and read by
them in full — and still not hold, because the moment it needed to bind was minutes or
hours after the moment it was read. A standing instruction lives in a brief, an onboarding
doc, a system prompt, or an agent's own working memory of a policy; the action it governs
happens later, under time pressure, in the middle of solving a different problem. By then
the rule is not "unknown," it is simply not *retrieved* — nothing at the point of the
action asks whether it applies.

This is a measured failure mode, not a hypothetical one, and it recurs identically at both
boundaries this package targets. On the git side: a correct, present, well-written rule
("never embed an absolute path," "never `git stash`," "no vendor attribution on a commit")
was violated anyway, repeatedly, because nothing stood between the intention and the
action to ask "does a rule apply here?" On the agent-turn side: a standing obligation
("every message opens with the right role label," "keep dispatching while there is ready
work," "the board should match what was actually dispatched") was adopted, correctly
stated, and still lapsed across a long session — because an announced action reads as a
taken one, a delivered report reads like the end of a turn, and a resumption point is
exactly where a self-applied habit is least likely to survive, because attention has just
been pulled elsewhere.

**The only mechanism that reliably closes this gap is one that does not depend on the
actor remembering anything: a check that runs automatically at the moment the action is
about to happen, and refuses it — or, where refusing is the wrong bias, surfaces an
unmissable reminder — regardless of who is acting or whether they meant to.** That is an
interlock. `interlock.git` is that mechanism at the git-action boundary; `interlock.turn`
is that mechanism at the agent-turn boundary. Neither is a second, unrelated tool that
happens to ship in the same distribution — they are the identical idea, aimed at the two
places a modern AI-assisted development loop actually needs it.

## Independent adoption — this is not an all-or-nothing framework

**Consolidating these into one distribution does not mean adopting one drags in the
other.** This is true in the code, not only in the prose below, and is proven — not just
asserted — by `tests/test_module_independence.py`, which physically deletes one host's
subpackage directory from a copy of this source tree and runs the other host's real
checks, as real subprocesses, against what remains.

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

### Path 3 — both together

Installing both is exactly path 1 and path 2 performed in the same repository, in either
order. Nothing about doing both changes what either one requires on its own — there is no
third, combined configuration format, no shared prerequisite state, and no "framework
mode" that activates once both are present. The only thing genuinely shared is described
below: one marker mechanism, one configuration *file* (each host reads only its own
section of it), and one CLI surface for managing both.

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

- **`interlock.turn`.** **This is the genuinely new half.** The framework this host was
  extracted from had no marker concept whatsoever — every hook, once wired into a
  harness's `settings.json`, simply ran, unconditionally, in every session that
  configuration reached. Consolidating onto `interlock.git`'s own marker primitive
  (`interlock.arming`) is how the turn-boundary host inherits that discipline: every hook
  in `interlock.turn` now checks its OWN per-worktree marker — stored in the exact same
  `git rev-parse --git-dir` location a git gate's marker lives in, written and read by the
  literal same function — before doing anything else. Unarmed means a silent no-op:
  no block, no reminder, nothing printed, exactly mirroring an unarmed git shim.

- **Where the two structurally cannot be identical, stated plainly rather than forced.**
  A git hook has a shim to install: a fixed file at a fixed, shared, single-file-per-event
  location git itself dispatches to. A turn-boundary hook has no such thing — an AI coding
  harness invokes whatever command its own hook configuration names, directly, with no
  git-style indirection layer in between. So `interlock.turn`'s WIRING (which command
  appears in `settings.json`) remains what it always was: a manual, disclosed edit you make
  yourself, documented in `docs/INTEGRATION.md`. `interlock install turn.<hook>` therefore
  arms the marker **and prints the exact `settings.json` entry to add**, rather than
  writing that file itself — advisory, never mutating, and it says so. What consolidation
  added is real and load-bearing (every turn hook is now silent-by-default until
  deliberately armed, per worktree); what it did not and structurally cannot add is a
  second "install once, shared" step, because there is no shared indirection file on the
  turn-host side to install into.

`interlock status` reports both facts — installed/wired, and armed — for every gate and
hook this distribution ships, or for one given by id. Conflating "installed" with
"therefore enforcing" is exactly the invisible gap arming exists to close; a status
command that only reported one of the two facts would reintroduce it in a different form.

### Naming a gate

An identifier has the shape `<host>.<name>` for the CLI (`git.protected-paths`,
`turn.idle-roster`), corresponding one-to-one with the check's own dotted Python module
path (`interlock.git.protected_paths`, `interlock.turn.idle_roster`).

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
(`interlock.plumbing`) rather than five independent, slowly-diverging copies of it.

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

## What genuinely became shared, and what stayed intentionally separate

Consolidation was not "put two folders next to each other." What actually moved into one
shared implementation:

1. **The install-and-arm marker mechanism** (`interlock.arming`) — one function set, used
   by `interlock.git.hookkit` for git gates and `interlock.turn.arming` for turn hooks
   alike. Proven, not just claimed: `tests/test_arming.py::TestGitAndTurnMarkersCoexist`
   arms one of each kind in the same worktree through the identical function and shows
   neither collides with the other.
2. **Git plumbing and repository-root discovery** (`interlock.plumbing`) — both hosts
   resolve "where is this repository" through the same function. This closed a genuine,
   if minor, latent defect: the turn host's predecessor package had its own,
   independently-written copy of "find the repository root" that called
   `subprocess.run(..., text=True)`, which decodes with the platform's default codepage
   (the Windows ANSI codepage, not UTF-8) rather than UTF-8 explicitly — harmless on an
   ASCII-only path, and exactly the kind of drift that consolidating onto one
   implementation rules out structurally rather than case by case.
3. **Configuration file and discovery** (`interlock.config`) — one JSON file,
   `interlock.json`, at the repository root, with one section per gate or hook that wants
   file-based configuration. `interlock.git`'s gates read their own section exactly as
   before (only the filename changed, from `action-boundary-gates.json`). `interlock.turn`
   stays primarily environment-variable-configured — see below for why that asymmetry is
   deliberate — but its one adopter-owned *structured* setting
   (`session_boundary_rows`, an id-to-reason exemption map) now also falls back to this
   same shared file's `"turn"` section, so an adopter already using `interlock.json` for
   the git side gets it without a second file to maintain.
4. **One CLI** (`interlock install|arm|disarm|status`) replacing five separate
   `--install`-flagged CLI modules on the git side and NO install/arm/status surface at
   all on the turn side.
5. **One versioning scheme, one `CHANGELOG.md`, one `RELEASE_PROCESS.md`.**

What stayed deliberately separate, because forcing symmetry would have been dishonest:

- **`interlock.turn`'s configuration stays environment-variable-primary.** A turn hook is
  invoked by the harness as a subprocess; the one thing every harness reliably lets an
  adopter control at that point is the subprocess's own environment, not a bespoke
  config-file convention this package would have to teach every harness about. See
  `interlock.turn.config`'s own module docstring.
- **`interlock.turn` has no shim to install**, because there is no shared,
  single-file-per-event indirection layer on that side to install into — see "The one
  install-and-arm discipline" above.
- **Fail-closed versus fail-open remain different, on purpose, per host.** See "Design
  principles" below.

## What this actually closes, measured rather than claimed

A framework that implies more coverage than it has is worse than one that claims less and
is right. Both halves of this package were developed against real, disclosed populations
of standing-constraint violations in an actual project — every incident where a correct,
present rule was not retrieved at the point it bound, over one measurement window of that
project's own history. Scored against that population, incident by incident, honestly, for
`interlock.git`'s own class of incident:

- **1 of 15** was an ownership-boundary violation this mechanism class both motivated and
  now prevents, armed and verified against a real repository.
- **4 of 15** were repeated invocations of a prohibited git subcommand that the
  `stash_invocation` gate mechanically solves — the predicate refuses every one of them
  identically — but which stay unprotected wherever the gate is built and never armed.
- **2 of 15** were "the team went idle with unblocked work sitting there," a class this
  package does not implement at the git-action boundary at all (it is exactly what
  `interlock.turn.idle_roster` targets instead, at the boundary where it IS observable).
- **8 of 15** were, and remain, permanently outside the reach of this mechanism class or
  any refusal-at-the-point-of-action mechanism — see "Residue classes" below.

That is **1 armed-and-reliable, 4 solved-but-unarmed, 2 addressed by the OTHER host in
this same distribution, 8 permanently unreachable, out of 15** — most of the 15 carrying
zero protection in practice at the time of measurement, because "solved" and "armed" are
different facts and a built-but-unarmed gate protects nothing. Arming what is already
solved closes real, measured exposure at effectively no further engineering cost.

**Do not read this as a verdict on the mechanism class in general.** It is a verdict on
one project's own measured incident population at one point in time, kept here because
publishing a rosier, unmeasured figure would be exactly the overstatement this section
exists to prevent. What transfers to a different project is the *method*: enumerate your
own real incidents, classify each as armed / solved-but-unarmed / reachable-by-a-different-
mechanism / permanently unreachable, and report the fraction rather than assume it.

`interlock.turn`'s own seven hooks were extracted the same way: each one closed one
specific, dated incident on that same project. The exact incident log is internal to that
project and is not reproduced here, but the *shape* of the incident each hook closes is
described in that hook's own module docstring, in this same distribution. Read the
docstring before relying on a hook for something its incident shape does not cover.

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

Both classes, on both hosts, are permanent, not merely unimplemented. Nothing proposed for
a future version of this package closes any of the four, and a roadmap that claimed
otherwise would be the overstatement this section exists to prevent.

### What was deliberately left out

The framework `interlock.turn` was extracted from carries an eighth hook — a
`PreToolUse` check that refuses a dispatch when a canonical worker-definition file and the
copy the harness actually reads have drifted. It is not included here: it depends on that
framework's own multi-repository, multi-directory skill-and-definition sync tool and that
tool's exact JSON report schema, and porting it faithfully means porting that whole sync
tool as a first-class feature of its own, not adapting a small hook. A future release may
add a generic version; until then, adopting this package means the freshness of whatever
standing worker-definition file you use is your own responsibility to keep in sync with
wherever your harness reads it from.

Five session-continuity *skills* (procedural documents a model reads when invoked, for
things like preparing a session for a context compaction and resuming cleanly afterward)
from the same source framework are also not included. They are deeply specific prose —
written throughout in terms of that framework's own multi-file session record, its own
governance layer, and its own two named hats — and turning them into genuinely portable,
adopter-agnostic procedures is a substantial rewriting effort in its own right, not a
find-and-replace. Leaving them out was judged better than shipping a rushed, lower-quality
generic version of nuanced procedural text.

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
  accident, and this is the sharpest asymmetry between the two hosts.** If a git gate
  cannot determine whether an action is safe, it refuses — an unverifiable action is not a
  verified one (`interlock.errors.GateError`). If a turn-boundary hook cannot read its
  transcript, its session record, or its payload, it does nothing and blocks nothing. This
  is not an inconsistency to fix; it reflects a real difference in what a false positive
  costs on each side. A blocked commit costs a `--no-verify` and a disclosed note. A
  turn-boundary hook that wedges every turn on any I/O hiccup gets disabled by its own
  operator within a day, and a disabled hook protects nothing at all.
- **The shim holds no logic** (git side). Everything a gate could get wrong lives in a
  tracked, tested Python module; the installed hook file is a small, fixed, byte-frozen
  shell script that only `exec`s that module.
- **Arm per worktree, wire once — on both hosts, per "The one install-and-arm
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
  never attempted there).
- **Configuration lives in as few places as each host's own constraints allow** — one
  shared file for anything file-based (`interlock.config`), environment variables where
  that is genuinely the only mechanism a harness reliably exposes
  (`interlock.turn.config`). A hook or gate module with a project-specific literal typed
  into its own logic is a bug in this package, not a feature of an adopter's fork.

## Where to go next

- **`docs/INTEGRATION.md`** — installing this into a real project: three separate
  adoption paths (git alone, turn alone, both), hook wiring, arming markers, and what to
  do if a `pre-commit` hook or a `settings.json` entry already exists.
- **`docs/USAGE.md`** — every configuration knob, the session-record schema, and how to
  author a new gate or hook of either class.
- **`CHANGELOG.md`** / **`RELEASE_PROCESS.md`** — versioning and how a release is cut.
- **`tests/`** — the full suite this README's claims are checked against, including
  `test_module_independence.py`'s physical proof of independent adoption; run it yourself
  (`python -m pytest tests` from this directory) before trusting anything above.

## License

Apache-2.0. See the `SPDX-License-Identifier` header on every source file in this
distribution.
