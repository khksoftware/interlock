# Integration manual

How to install Interlock into a repository that is not this one. Read `README.md` first
if you have not — it explains what this is and why it exists; this document is only the
mechanics of turning it on.

**Read this whole document even if you only want one host.** Sections 1–5 are
`interlock.git`; sections 6–9 are `interlock.turn`; section 10 covers what changes (almost
nothing) when you run both. Each host's own sections say so at the top, and neither
requires you to read the other's.

---

## Part A — `interlock.git` (independently adoptable; no agents required)

### 1. Get the package on the interpreter you will arm with

Every gate's hook shim ends with `exec "$gate_python" -B -m interlock.git.cli....` —
`$gate_python` is read from that worktree's own arming marker (see §3), and whatever
interpreter that is must be able to `import interlock`. Two ways to arrange that:

- **Install it properly** (recommended for real use): `python -m pip install -e
  /path/to/this/distribution` (or, once published, `pip install interlock` — see
  `RELEASE_PROCESS.md` on the distribution name not yet being confirmed available) into
  the interpreter you intend to arm with. This is the only step that survives moving or
  cleaning up the distribution's own checkout afterward.
- **Point `PYTHONPATH` at its `src/` directory** without installing anything — the
  fastest way to try this out, and what this package's own test suite does internally
  (`conftest.py` at the root of this distribution). Set `PYTHONPATH` for the *shell you
  arm from*, not globally, unless you want every Python process on the machine to see
  this package.

Either way, confirm it before wiring any hook:

```bash
python -c "import interlock; print(interlock.__version__)"
```

### 2. Configure what each gate protects (three of the five need this)

Two gates need no configuration at all: `stash_invocation` (its rule is fixed — never
stash) and `synthetic_git_identity` (its rule is fixed — never commit under a reserved
documentation domain). The other three read a small, adopter-owned JSON file at the root
of the repository being protected, `interlock.json` — track it, it is ordinary project
content:

```json
{
  "protected_paths": {
    "paths": ["config/production-secrets.enc"],
    "prefixes": ["legal/", "vendor/"]
  },
  "absolute_local_path": {
    "citations": [
      {"path": "docs/incident-2024-06.md", "line_contains": "reproduced under the on-call engineer's home directory"}
    ],
    "deferred_scope": [
      {"path_prefix": "fixtures/"}
    ]
  },
  "commit_message_pattern": {
    "trailer_keys": ["co-authored-by"]
  }
}
```

A repository with no such file, or no section for a given gate, gets that gate's safe
default — for `protected_paths`, that means it protects *nothing* (it has no opinion
about your repository until you configure one); for `absolute_local_path`, the built-in
path patterns apply with no exemptions; for `commit_message_pattern`, the built-in
vendor/AI-attribution preset applies (see `interlock.git.commit_message_pattern` for the
full default list and how to replace it with your own trailer keys and patterns — a
custom forbidden-pattern list is a Python-level argument, not a JSON one, since compiled
regexes do not round-trip through JSON).

Every gate's own CLI also accepts `--config <path>` if you want the file somewhere else,
and every predicate function accepts its configuration directly as Python arguments for a
caller that does not want a JSON file at all.

**If you also adopt `interlock.turn`, this is the same file** — see §10. Nothing here
requires that section to exist, or vice versa.

### 3. Install and arm

From inside the repository you are protecting, once per gate — either the unified CLI:

```bash
interlock install git.protected-paths
interlock install git.absolute-local-path
interlock install git.synthetic-git-identity
interlock install git.commit-message-pattern
```

or the equivalent per-gate module form, which is exactly what the unified CLI calls
underneath and remains available directly:

```bash
python -B -m interlock.git.cli.check_protected_paths --install
```

`install` does two things, and they are deliberately separable (see `interlock arm`, or
`arm_marker()` in `interlock.git.hookkit`, for the additive half on its own):

1. Writes that gate's fixed shell shim into the shared hooks directory
   (`git rev-parse --git-common-dir`/`hooks`), unless something else already occupies
   that hook name — see §5 below if it does.
2. Writes a marker file into *this worktree's own* git directory
   (`git rev-parse --git-dir`) recording the interpreter to run the gate with.

`stash_invocation` uses `reference-transaction` instead of `pre-commit`/`commit-msg`, and
**installing it is a separate, deliberate decision** from installing the other four: a
`reference-transaction` hook fires on every ref update in every worktree it reaches,
including things you may not have anticipated (see §4). Nothing in this package installs
it automatically as a side effect of installing anything else.

### 4. Per-worktree vs. shared git-directory concerns

- **Hooks are shared by every worktree of a repository.** `git rev-parse
  --git-common-dir` resolves to the SAME directory no matter which linked worktree
  (`git worktree add`) you run it from. Installing a hook from one worktree makes it fire
  in every other worktree of that same repository.
- **The arming marker is per-worktree.** `git rev-parse --git-dir` resolves to a
  DIFFERENT directory for each linked worktree. A repository with five worktrees can have
  a gate armed in two of them and not the other three — a normal, supported, disclosed
  state, not a bug.
- **`core.hooksPath`, if set, changes where the shim goes** (and where git looks for it),
  but it is still one shared location, not a per-worktree one.
- **A fresh clone has none of this.** Hooks are never tracked by git, so a new clone has
  no hook installed at all until someone runs `install` in it again. If every clone must
  come pre-armed, that has to happen in your own onboarding/bootstrap tooling.

### 5. What to do when a `pre-commit` hook already exists

Three of the five gates (`protected_paths`, `absolute_local_path`,
`synthetic_git_identity`) use `pre-commit`. Git dispatches exactly one file per hook name,
so if your repository already has a `pre-commit` hook, `install` **refuses rather than
silently overwrites it**:

```
GateError: a pre-commit hook that is not this shim is already installed at .../hooks/pre-commit;
refusing to overwrite it.
```

Three honest options, in order of how much this package assumes for you:

1. **Compose by hand.** Write your own `pre-commit` file that checks each gate's own
   marker and `exec`s each gate's own CLI in turn. `tests/git/test_hookkit.py`'s
   `TestComposingTwoPreCommitGatesOntoOneSharedHook` class is a complete, runnable
   example — copy its composed shim shape. Then arm each gate's marker with
   `interlock arm git.<gate>` (not `install`, which would try to write the shim again and
   hit the same refusal).
2. **Delegate to another framework that supports multiple hooks natively** (e.g. the
   pre-commit framework at pre-commit.com) by wrapping each gate's CLI as one of its
   entries.
3. **Pick one `pre-commit` owner and have it shell out to the others** — the smallest
   change if your existing hook is already a shell script.

`commit-msg` and `reference-transaction` are far less commonly already occupied, but the
same refusal-rather-than-overwrite behaviour and the same three options apply.

### Verifying a gate is actually armed, not just installed

```bash
interlock status git.protected-paths
```

Or drive a real, known-bad fixture through a real `git commit` and confirm it is actually
refused — the only fully convincing proof, and the one every test in `tests/git/` is
built on.

### Uninstalling

`interlock disarm git.<gate>` removes the arming marker (disarms one gate in one worktree
without touching anything shared). Removing the shim file from the shared hooks directory
turns the hook off entirely, for every worktree — do this only when you mean every
worktree.

---

## Part B — `interlock.turn` (independently adoptable; no git-side gates required)

### 6. Install and confirm the stdin/stdout contract

```bash
python -m pip install -e /path/to/this/distribution
```

An editable install is recommended: it lets you override `interlock.turn.config`'s
defaults by setting environment variables in your harness's own process environment
without reinstalling for every configuration change.

Every hook module in `interlock/turn/` is a small, standalone script with a `main()`
function:

1. Reads a single JSON object from stdin (the harness's own hook payload). A missing,
   empty, or malformed stdin is handled gracefully — the hook exits `0` with no output.
2. Optionally prints a single JSON object to stdout: `{"decision": "block", "reason":
   "..."}` to refuse the turn (a `Stop` hook), `{"systemMessage": "..."}` for a
   non-blocking message, or `{"hookSpecificOutput": {...}}` for a reminder-only hook
   (`user_prompt_submit.py`).
3. Always exits `0`. A hook's own crash or malformed input is never how it communicates
   a refusal.

This is the contract Claude Code's own hook system uses; a different harness may differ —
confirm your own harness's documented hook payload and verdict shape, and see "Adapting
to a different harness" below if it does.

### 7. Wiring into Claude Code

```json
{
  "hooks": {
    "SubagentStart": [
      { "hooks": [{ "type": "command", "command": "python -m interlock.turn.subagent_start" }] }
    ],
    "SubagentStop": [
      { "hooks": [{ "type": "command", "command": "python -m interlock.turn.subagent_stop" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python -m interlock.turn.user_prompt_submit" }] }
    ],
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python -m interlock.turn.announced_action" },
        { "type": "command", "command": "python -m interlock.turn.role_label" },
        { "type": "command", "command": "python -m interlock.turn.idle_roster" },
        { "type": "command", "command": "python -m interlock.turn.roster_reconciliation" }
      ]}
    ]
  }
}
```

Order within the `Stop` array does not matter functionally — each hook is independent and
every one short-circuits immediately when the payload's `stop_hook_active` is already
set, so a block from one cannot cause another to loop.

**This file is a manual, disclosed edit you make yourself.** Nothing in this package
writes it for you — see "The one install-and-arm discipline" in `README.md` for precisely
why that is a structural fact about turn-boundary hooks, not a missing feature.

### 8. Arming — the part that is genuinely new here

Wiring a hook into `settings.json` is not enough on its own: every hook also checks its
own per-worktree marker before doing anything, exactly mirroring a git gate's shim.

```bash
interlock arm turn.role-label
interlock arm turn.idle-roster
# ... one per hook you wired in.

interlock install turn.role-label   # arms AND prints the settings.json entry to add,
                                     # as a reminder -- it never writes settings.json itself.
```

An unarmed hook, once wired, still runs on every turn — reads its payload, checks its own
marker, finds none, and exits 0 with no output at all. Nothing blocks, nothing reminds,
until you arm it. `interlock status turn.<hook>` reports both facts (wired is a
self-reported "see your own settings.json"; armed is checked directly against this
worktree's marker).

### The session record

`idle_roster.py` and `roster_reconciliation.py` both read one JSON file — see
`interlock.turn.session_record`'s own module docstring for its full schema and an
example. By default this package looks for it at `.interlock/session_record.json`
relative to the repository root; override the path with `INTERLOCK_SESSION_RECORD_PATH`
(see `docs/USAGE.md`). Nothing in this package writes that file — maintaining it
(typically by having your supervisor agent read and rewrite it as part of its own turn) is
entirely your own responsibility. A missing or malformed record is treated as a scope
miss (both hooks return cleanly with no output), not an error, but the two hooks provide
no supervision at all until an equivalent record exists.

**Only these two hooks need the session record.** `role_label`, `announced_action`,
`subagent_start`, `subagent_stop`, and `user_prompt_submit` have no dependency on it at
all — you can arm any of those five alone and never create a session-record file.

### Verifying the wiring took

```bash
# 1. A trivial dispatch should populate the outstanding-agent registry, then clear it.
interlock arm turn.subagent-start && interlock arm turn.subagent-stop
echo '{"agent_id": "test-1", "description": "smoke test"}' | python -m interlock.turn.subagent_start
cat ~/.interlock/outstanding-agents.json   # should show one entry
echo '{"agent_id": "test-1"}' | python -m interlock.turn.subagent_stop
cat ~/.interlock/outstanding-agents.json   # should be empty again

# 2. A transcript ending on an unlabelled message should refuse (after arming turn.role-label).
interlock arm turn.role-label
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"no label here"}]}}' > /tmp/t.jsonl
echo '{"transcript_path": "/tmp/t.jsonl", "stop_hook_active": false}' | python -m interlock.turn.role_label
# -> {"decision": "block", "reason": "ROLE LABEL MISSING OR MALFORMED ..."}
```

If a hook prints nothing when you expected a block or reminder: first confirm it is
ARMED (`interlock status`) — the single most common reason in this package's own history
of running it, since arming is new — then confirm `PYTHONPATH`/the editable install, then
confirm the payload shape matches what that hook's own docstring documents.

### 9. Adapting to a different harness

Every hook here was built against Claude Code's own observed hook payload shapes. A
different harness will very likely use different field names, event naming, or verdict
format. Before wiring a hook into a harness other than Claude Code:

1. Confirm the actual JSON payload shape your harness sends for the closest equivalent of
   each event.
2. Confirm how your harness reads a hook's stdout.
3. Expect to adapt the small amount of payload-parsing code at the top of each hook's
   `main()` while reusing `config.py`, `outstanding.py`, `session_record.py`, and
   `arming.py` unchanged.

---

## Part C — running both together

Nothing extra to configure beyond Parts A and B, each performed once. The only point of
contact:

- **`interlock.json`, if you use it for both.** `interlock.git`'s gates read
  `protected_paths` / `absolute_local_path` / `commit_message_pattern` sections;
  `interlock.turn`'s `session_boundary_rows` setting reads a `"turn"` section as a
  fallback beneath its own environment-variable override. Neither host requires the
  other's section to exist.
- **The arming markers live in the same directory** (`git rev-parse --git-dir`) but under
  different names (`interlock-git-<gate>` vs. `interlock-turn-<hook>`) — `interlock
  status` with no id lists every one, from both hosts, together.
- **`interlock.registry` and `interlock.cli`** are the only modules that import both
  hosts (see that module's own docstring) — this is expected, and is the one place doing
  so is the point rather than a violation of independence.
