# Usage manual

Every configuration knob any host reads, the session-record schema `interlock.turn`'s two
roster hooks depend on, and how to author a new gate or hook of any class. Read
`README.md`'s "Design principles" section first — this document assumes it.

---

## Part A — authoring a new `interlock.git` gate

### Step 0 — is this actually an action-boundary gate?

Before writing any code, check the candidate against the same test this package's own
gates were screened by:

1. **Is there a real, disclosed incident this would have caught?** A gate built on an
   imagined failure mode, with no evidence anyone has ever actually hit it, is exactly
   the disproportionate control this mechanism class exists to avoid manufacturing. If
   you cannot point to a concrete case, write the rule down as policy instead and wait
   for evidence.
2. **Is the thing you want to refuse actually observable at a git-hook boundary?** Not
   every rule is. "Don't use `git add -A`" is not observable — by the time any hook runs,
   an `-A`-built index looks identical to one built by naming exact paths. "Don't leave
   `.git/index.lock` around" is not observable — removing a lock file has no git-hook
   event at all. `interlock.git.stash_invocation`'s own docstring is a worked example of
   finding the ONE hook (`reference-transaction`) that actually sees an action
   (`git stash`) after two more obvious candidates turned out to see nothing of it.
3. **Which of git's hook points is the last one before the action becomes permanent?**
   `pre-commit` for staged file content, `commit-msg` for the message,
   `reference-transaction` for any ref update including stash. If your subject fits none
   of git's documented hook points (`githooks(5)`), it may belong to one of this
   package's own residue classes instead (see `README.md`) — or to `interlock.turn`, if
   the thing you actually want to catch is an agent's own turn ending on an unfulfilled
   obligation rather than a git action at all.

### Step 1 — write the predicate as a pure(-ish) function

Every existing gate follows the same shape: one function that takes a repository root
(and whatever configuration it needs) and returns a tuple of human-readable failure
strings — empty means clean. Keep I/O to git plumbing calls only (`commit_paths`,
`index_blob`, `effective_git_config` from `interlock.plumbing`), so the function is
directly unit-testable against a throwaway sandbox repository. See
`interlock.git.protected_paths` for the shortest complete example.

**Scope your predicate to what the action itself carries, never to a repository-wide
walk.**

### Step 2 — declare a `GateSpec` and render (or hand-write) the shim

```python
from interlock.git.hookkit import GateSpec, render_shim

GATE_LABEL = "my-new gate"
GATE_MARKER_NAME = "interlock-git-my-new-gate"   # unique across every gate you run together
HOOK_NAME = "pre-commit"                          # or commit-msg / reference-transaction
CLI_MODULE = "interlock.git.cli.check_my_new_gate"

SPEC = GateSpec(
    marker_name=GATE_MARKER_NAME,
    hook_name=HOOK_NAME,
    shim=render_shim(
        marker_name=GATE_MARKER_NAME, hook_name=HOOK_NAME, cli_module=CLI_MODULE,
        gate_label=GATE_LABEL,
    ),
)
```

Use `render_shim`'s `forwards_hook_arguments=True` if your hook takes positional
arguments. `interlock.git.stash_invocation` hand-writes its own shim instead, because
`reference-transaction`'s calling convention (stdin must be inherited automatically by
`exec`) does not fit the generic helper's default shape.

**Never embed a machine-specific path in the shim.** The interpreter goes in the
per-worktree marker, written at arming time — see `tests/git/test_hookkit.py::TestRenderShim::test_shim_embeds_no_machine_specific_path`.

### Step 3 — write the CLI

Copy the shape of an existing `interlock/git/cli/check_*.py` module closest to your
gate's own signature. The contract every CLI keeps: three exit codes (0 clean, 1 refused,
2 the gate itself could not run), `--repository-root`, `--install`, `--interpreter`, and a
refusal message naming the escape hatch (`--no-verify`).

### Step 4 — prove it red, then green

In a throwaway `git init` sandbox (`tests/conftest.py`'s `sandbox` fixture):

1. **Red, on the predicate alone.** Assert a non-empty tuple against a fixture shaped
   exactly like the real incident.
2. **Green, on the predicate alone.** The identical repository, minus the one thing your
   predicate objects to.
3. **Red, on the real, installed hook.** `install()` your `SPEC`, arm it, drive a REAL
   `git commit` (or `git stash`) with the bad fixture staged. Assert non-zero exit.
4. **The un-armed control.** The identical bad fixture, never installed. Assert the
   commit SUCCEEDS.
5. **The bypass control.** `git commit --no-verify` against the armed fixture succeeds.
   State this in your gate's own documentation.

`tests/git/test_protected_paths.py`'s `TestTheBlockActuallyBlocks` class is a complete,
runnable template for steps 3–5.

### Step 5 — register it with the unified CLI (optional, but recommended)

Add an entry to `interlock.registry.GIT_GATES` so `interlock install|arm|disarm|status`
covers your new gate too — see that module's own docstring for the id-naming convention.

---

## Part B — authoring a new `interlock.turn` hook

### Configuration (environment variables)

Every adopter-specific value is read from an environment variable, with a generic
default, in `interlock.turn.config`. Set these in whatever environment your harness runs
hook subprocesses in.

| Variable | Default | Controls |
|---|---|---|
| `INTERLOCK_SUPERVISOR_LABEL` | `[Supervisor]` | The role label the operator-facing hat must open every message with. |
| `INTERLOCK_WORKER_LABEL` | `[Worker]` | The role label a delegated worker's hands-on messages open with. |
| `INTERLOCK_SESSION_RECORD_PATH` | `.interlock/session_record.json` | Path to the session record `idle_roster.py`/`roster_reconciliation.py` read, relative to the repository root unless absolute. |
| `INTERLOCK_QUIESCING_COMMANDS` | `wrap-up,prepare-to-pause` | Comma-separated command/skill names whose recent presence in the transcript suppresses both roster hooks entirely. Empty disables suppression. |
| `INTERLOCK_ID_PATTERN` | `[A-Z][A-Z0-9]{1,9}-\d{1,6}` | Regular expression (case-insensitive) matching your board/ticket id shape, used by `roster_reconciliation.py`. |
| `INTERLOCK_SESSION_BOUNDARY_ROWS_PATH` | *(empty)* | Path to a JSON object (`{"id": "reason"}`) of board-item ids `idle_roster.py` should treat as genuinely not dispatchable, relative to the repository root unless absolute. Empty means: fall back to the shared `interlock.json`'s `"turn"` section (see below), then to no exemptions. |
| `INTERLOCK_OUTSTANDING_REGISTRY_PATH` | `~/.interlock/outstanding-agents.json` | Where `subagent_start.py`/`subagent_stop.py`/`user_prompt_submit.py` keep the best-effort outstanding-agent registry. |
| `INTERLOCK_OUTSTANDING_STALE_SECONDS` | `21600` (6 hours) | How long an outstanding-registry entry may sit before `user_prompt_submit.py` treats it as stale and prunes it rather than reminding about it. |
| `INTERLOCK_RESUMPTION_COMMANDS` | `/resume,/compact,/clear` | Comma-separated prompt prefixes after which `user_prompt_submit.py` escalates its role-label reminder. |

**`session_boundary_rows` is the one setting also readable from the shared
`interlock.json`** (see `README.md`'s "What is shared" section):

```json
{
  "turn": {
    "session_boundary_rows": {
      "PROJ-101": "genuinely blocked on an external release window"
    }
  }
}
```

An explicit `INTERLOCK_SESSION_BOUNDARY_ROWS_PATH` always wins over this fallback.

### The session record

`idle_roster.py` and `roster_reconciliation.py` both read one JSON file. The simplest
valid shape, for an adopter with a single agent platform:

```json
{
  "roster": {
    "state": "none",
    "entries": []
  },
  "queue": [
    { "id": "PROJ-101", "status": "queued", "sequenced": true }
  ]
}
```

- **`roster.state`** is one of three values, never collapsed into each other: `"none"`
  (something looked and found nothing running — the only state that counts as *verified
  empty*), `"not-observable"` (nobody could look — must never be read as idle capacity),
  or `"enumerated"` (a real, current list of running agents is in `roster.entries`, each
  typically at least `{"id": "..."}`).
- **`queue`** is a flat list of work rows. A row is dispatchable when `status` is
  `"queued"`, `sequenced` is `true`, and `blocked_on` is absent or empty. `id` is matched
  case-insensitively against `INTERLOCK_ID_PATTERN` when cross-referencing a live
  dispatch's own free-text description.

An adopter running more than one agent platform against the same repository wraps the
same shape per platform:

```json
{
  "platforms": [
    { "platform": "claude-code", "roster": { "state": "none", "entries": [] }, "queue": [ /* ... */ ] },
    { "platform": "codex", "roster": { "state": "enumerated", "entries": [{"id": "worker-3"}] }, "queue": [ /* ... */ ] }
  ]
}
```

Nothing in this package writes this file. Maintaining it is entirely your own
responsibility; see `docs/INTEGRATION.md` for what happens when it is missing or
malformed (a silent scope miss, not an error).

### Authoring a new hook of this class

1. **State what incident it closes**, concretely, in the module's own docstring — a hook
   with no named incident is a rule looking for a violation rather than a fix for a
   measured one.
2. **State what it can and cannot prove**, in the same docstring, before writing a single
   line of the check itself.
3. **Read the payload from stdin, print a verdict to stdout, always exit 0.** Never let
   the check's own internal failure be indistinguishable from a hard block.
4. **Check your own arming marker FIRST, before anything else in `main()`.** See
   `interlock.turn.arming` and copy the one-line pattern every existing hook opens with:
   `if not arming.is_armed("your_hook_name"): return 0`. Add your hook's key to
   `interlock.turn.arming.HOOK_MARKER_NAMES` and to `interlock.registry.TURN_HOOKS`.
5. **Read configuration through `config.py`, never hardcode a project-specific value.**
6. **Test it red, then green, against a real fixture repository and a real synthetic
   transcript.** `tests/turn/conftest.py`'s `sandbox` fixture and its
   `write_transcript`/`write_session_record`/`dispatch_entry`/`notification_entry`
   helpers are built for exactly this. `run_hook_subprocess` ARMS your hook by default
   before invoking it — pass `armed=False` for the dedicated unarmed-is-silent test every
   existing hook's test module carries.
7. **Prove a suite that always passes is not silently skipping the real check.** A test
   that asserts "did not block" without first proving the corresponding "did block" case
   exists proves nothing.

---

## Part C — `interlock.guard`: configuration surface and extending the rule set

### Configuration (environment variables)

| Variable | Default | Controls |
|---|---|---|
| `INTERLOCK_GUARD_STATE_DIR` | `~/.interlock/guard` | Where a recorded approval, its consumed-approval record, and the audit log (`events.jsonl`) are kept. |
| `INTERLOCK_GUARD_DEFAULT_APPROVAL_EXPIRY_MINUTES` | `30` | How long a recorded approval remains usable before it expires, unless a caller of `record_approval` passes `--expires-minutes` explicitly (1–1440). |

Both are read fresh on every call, not frozen at import time — a caller that records an
approval in-process and then drives the real hook as a separate subprocess needs both to
resolve the identical state directory from the identical environment variable read at the
moment each one actually runs.

### What a rule is

Every rule this hook recognizes is one entry in `execution_guard.classify_command`: a
regular expression (or small combination of them) over the command text, an `activity`
description, and a cheaper `alternative` to suggest. The built-in set (`COST-WORKTREE-ADD`,
`COST-FULL-TREE-SCAN`, `COST-FULL-TEST-SUITE`, `COST-BROAD-TEST-CLOSURE`,
`COST-DATABASE-COPY`, `COST-RECURSIVE-HASH`) recognizes only shapes whose broad scope is
visible in the command text itself, before execution — this is a deliberately small
guardrail, not a cost oracle, and an ambiguous command matching none of them is not
evidence it is cheap.

**A heredoc's or here-string's payload is stripped before a rule is evaluated only when
stripping cannot hide a command that will actually execute** (`strip_payload_bodies`): a real
closing terminator must be confirmed, the opening line must not feed the body to a
recognized shell/PowerShell interpreter, and the heredoc's own `<<` must be confirmed to sit
outside any quoted text (tracked across lines, aware of a backslash-escaped quote). When all
three hold, a rule sees the invocation shape itself, never content a command happens to be
writing out; when any one does not, the body is left visible rather than risk silently
discarding a genuine command. See `README.md`'s Limits section for what this still does not,
and cannot fully, close: a finite, named list of recognized interpreters, and a
character-level approximation of shell quoting rather than a full grammar parser. Extend the
rule set by adding a case to `classify_command`, following the existing entries' shape
exactly: a regex over the lower-cased, backslash-normalized text, an `activity`, and an
`alternative` naming the cheaper path. Test both directions — the matching shape blocks, and
the closest safe neighbour (an exact single file, an existing worktree, a targeted query)
does not.

### How an approval is recorded, and how long one lasts

`record_approval(sha256, *, reason, alternatives, baseline_plan, expires_minutes=None)`
writes one JSON receipt under `INTERLOCK_GUARD_STATE_DIR/approvals/<SHA256>.json`,
requiring `reason`, `alternatives_considered`, and `baseline_reuse_plan` to all be
non-empty — an approval with no stated reason is indistinguishable from a self-authorized
bypass, so the hook refuses to record one. `uses_remaining` is always `1`: an approval is
consumed the first time the exact, unchanged command is retried
(`consume_approval`), moved to `INTERLOCK_GUARD_STATE_DIR/consumed/`, and cannot be reused.
It also expires after `expires_minutes` (default from
`INTERLOCK_GUARD_DEFAULT_APPROVAL_EXPIRY_MINUTES`) regardless of whether it was ever
consumed. Every block and every consumed-approval event is appended to
`INTERLOCK_GUARD_STATE_DIR/events.jsonl` as a hashed record — the command's SHA-256 and the
matched rule ids, never the command's own text, so the audit log itself never becomes a
second place a sensitive command string is retained.

### Authoring a new guard hook of this class

The same seven steps Part B lists apply here essentially unchanged, with two
guard-specific substitutions: check `interlock.guard.arming.is_armed("your_hook_name")`
rather than the turn module's, and add your hook's key to
`interlock.guard.arming.HOOK_MARKER_NAMES` and to `interlock.registry.GUARD_HOOKS` rather
than their turn-side counterparts. `tests/guard/test_execution_guard.py` is the template
to copy for red/green predicate coverage plus a real armed/unarmed subprocess proof.
