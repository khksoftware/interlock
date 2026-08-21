# SPDX-License-Identifier: Apache-2.0
"""The git-specific half of installation: a shell shim, and refusing to overwrite a
foreign hook. Builds on :mod:`interlock.arming` for the per-worktree marker half
-- read that module first if you have not; everything below assumes the discipline it
documents.

## Why a shim at all, rather than writing the check straight into ``hooks/<name>``

Git hook files are untracked by convention and by git's own design (see ``githooks(5)``):
nothing under version control records that a hook exists, what it does, or that it
changed. An installed hook that is also where the logic lives is therefore unreviewable
and undiffable -- a change to it leaves no trace anyone else can see. Every gate in
`interlock.git` instead installs a tiny, fixed, byte-frozen shim (:data:`GateSpec.shim`)
that holds no logic at all; everything the shim could get wrong lives in the tracked,
tested Python module the shim ``exec``s. A test that asserts the installed file is
byte-identical to the shim the tracked module carries turns "is this gate actually armed"
into a mechanical, verifiable fact instead of something someone has to remember to check.

## Why the interpreter lives in the marker, never in the shim

The shim is the same, fixed text on every machine and in every repository this package is
installed into -- it embeds no machine-specific path. The interpreter to run the gate's
own Python module with is instead written into the per-worktree marker file at arming
time. This matters beyond tidiness: a gate whose job includes refusing an embedded local
filesystem path in a commit (see
:mod:`interlock.git.absolute_local_path`) would be enforcing a rule
its own installation mechanism violates, if the mechanism itself wrote such a path into a
file this package tracks or installs.

## Why `interlock.turn` does not use this module

`interlock.turn`'s own hooks have no shim to install: an AI coding harness invokes
whatever command a `settings.json`-style configuration names, directly -- there is no
git-style single-file-per-event indirection to write into. `interlock.turn.arming` reuses
this module's underlying marker primitives (from :mod:`interlock.arming`) for the ARMING
half only; it has no counterpart to `GateSpec`, `render_shim`, or `install`'s shim-writing
step, because there is no shim. See that module's own docstring for the precise statement
of where the two hosts' arming discipline is identical and where it structurally cannot
be.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interlock import arming
from interlock.errors import GateError
from interlock.plumbing import hooks_directory, worktree_git_dir


@dataclass(frozen=True)
class GateSpec:
    """Everything the shared installer needs to know about one gate.

    ``marker_name`` and ``hook_name`` are read directly by the generic functions below.
    ``shim`` is the exact, byte-for-byte content this gate wants installed at
    ``<hooks_directory>/<hook_name>`` -- render it once with :func:`render_shim` (or
    hand-write it, if a gate's own hook takes an unusual calling convention) and treat it
    as a frozen constant from then on, exactly as every gate module in this package does.
    """

    marker_name: str
    hook_name: str
    shim: str


def render_shim(
    *, marker_name: str, hook_name: str, cli_module: str, gate_label: str,
    forwards_hook_arguments: bool = False,
) -> str:
    """Build a standard shim body for a gate whose CLI takes no special hook-supplied
    input, or forwards it verbatim as positional arguments.

    Most gates can use this directly. A gate whose hook has an unusual calling convention
    (``reference-transaction`` is the one built-in example -- see
    :mod:`interlock.git.stash_invocation`, which forwards ``"$@"``
    and relies on stdin being inherited automatically) may instead hand-write its own
    ``shim`` constant; nothing requires this helper to be used, it only removes
    boilerplate for the common case.
    """
    forward = ' "$@"' if forwards_hook_arguments else ""
    return f"""#!/bin/sh
# interlock (git): {gate_label}. INSTALLED, NOT TRACKED.
#
# This file deliberately holds no logic. Everything it could get wrong lives in the tracked,
# tested Python module this shim execs, and that module's own test suite asserts this file is
# present and byte-identical to the shim it carries -- so a checkout with no gate installed
# reports a red on the first test run instead of being an invisible absence.
#
# Hooks resolve to the git COMMON directory, so this fires in every worktree of a repository
# it is installed into, including one an unrelated stream owns. It therefore refuses to
# enforce anywhere it was not explicitly armed. The arming marker lives in the PER-WORKTREE
# git directory, which `git rev-parse --git-dir` resolves separately for each worktree; an
# unarmed worktree exits 0 having loaded nothing.
#
# The marker also carries the interpreter, which is why this shim is identical on every
# machine that installs it and embeds no machine-specific filesystem path.
set -e
gate_dir="$(git rev-parse --git-dir)"
gate_marker="$gate_dir/{marker_name}"
[ -f "$gate_marker" ] || exit 0
gate_python="$(cat "$gate_marker")"
if [ ! -f "$gate_python" ]; then
    printf '%s\\n' "{gate_label}: the recorded interpreter is absent: $gate_python" >&2
    printf '%s\\n' "reinstall with: <interpreter> -m {cli_module} --install" >&2
    printf '%s\\n' "the action is refused rather than passed unchecked." >&2
    exit 1
fi
exec "$gate_python" -B -m {cli_module}{forward}
"""


def gate_marker_path(root: str | Path, spec: GateSpec) -> Path:
    """This worktree's own arming marker for ``spec`` -- present iff this worktree is
    armed."""
    return arming.marker_path(root, spec.marker_name)


def installed_hook_path(root: str | Path, spec: GateSpec) -> Path:
    """Where ``spec``'s shim belongs in the shared hooks directory."""
    return hooks_directory(root) / spec.hook_name


def is_armed(root: str | Path, spec: GateSpec) -> bool:
    """Whether THIS worktree has armed ``spec``. Says nothing about any other worktree."""
    return arming.is_armed(root, spec.marker_name)


def install(root: str | Path, spec: GateSpec, *, interpreter: str | Path) -> tuple[str, ...]:
    """Write ``spec``'s shim into the shared hooks directory and arm THIS worktree only.

    **Refuses rather than overwrites a foreign hook.** If something other than this exact
    shim already occupies ``<hooks_directory>/<hook_name>``, this raises rather than
    clobbering it -- another gate (see ``docs/INTEGRATION.md`` on composing several gates
    onto the same hook name) or a pre-existing project hook may already live there, and
    this package has no authority to decide how the two should coexist. Idempotent when
    the installed hook is already this exact shim.
    """
    root = Path(root)
    interpreter = Path(interpreter)
    if not interpreter.is_file():
        raise GateError(f"the interpreter to record does not exist: {interpreter}")
    actions: list[str] = []
    hook = installed_hook_path(root, spec)
    hook.parent.mkdir(parents=True, exist_ok=True)
    if hook.is_file():
        # Byte-exact. Deliberately not `read_text(newline="")`: that keyword reached
        # `Path.read_text` only in Python 3.13, so on an older, still-supported interpreter
        # it is a TypeError rather than a strict read.
        existing = hook.read_bytes().decode("utf-8", errors="replace")
        if existing != spec.shim:
            raise GateError(
                f"a {spec.hook_name} hook that is not this shim is already installed at "
                f"{hook}; refusing to overwrite it. Something else may own it -- inspect it, "
                "and if it is genuinely stale remove it deliberately before reinstalling. "
                "See docs/INTEGRATION.md if you need this gate to coexist with an existing "
                "hook of the same name."
            )
        actions.append(f"hook already current: {hook}")
    else:
        hook.write_text(spec.shim, encoding="utf-8", newline="")
        hook.chmod(0o755)
        actions.append(f"hook installed: {hook}")
    # Forward slashes: the marker is read by `sh`, where a backslash inside double quotes is
    # an escape character rather than a path separator.
    recorded = interpreter.resolve().as_posix()
    actions.append(arming.arm(root, spec.marker_name, recorded))
    return tuple(actions)


def arm_marker(root: str | Path, spec: GateSpec, *, interpreter: str | Path) -> str:
    """Write only this gate's own per-worktree marker, without touching the hook file.

    The additive counterpart to :func:`install`, for the case documented in
    ``docs/INTEGRATION.md``: composing several gates' shims into one physical hook file by
    hand (because git dispatches exactly one file per hook name), where arming a newly-added
    gate must not require rewriting a hook file some other installer already composed and
    owns.
    """
    root = Path(root)
    interpreter = Path(interpreter)
    if not interpreter.is_file():
        raise GateError(f"the interpreter to record does not exist: {interpreter}")
    recorded = interpreter.resolve().as_posix()
    return arming.arm(root, spec.marker_name, recorded)


__all__ = (
    "GateSpec", "arm_marker", "gate_marker_path", "install", "installed_hook_path",
    "is_armed", "render_shim",
)
