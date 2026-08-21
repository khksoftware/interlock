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

## Composing more than one gate onto a shared hook name

Git dispatches exactly one file per hook name, and three of this package's own five gates
(`protected_paths`, `absolute_local_path`, `synthetic_git_identity`) all use `pre-commit` --
so a second `install` targeting an already-occupied hook name used to refuse outright,
unconditionally, even when the thing already occupying it was this package's own other
gate (see `REVIEW_2026-08-21.md`, Findings 2 and 3: the README's own quickstart lists all
three back to back, and the two docs disagreed about how a reader was supposed to get out
of the resulting refusal). :func:`install` now composes automatically instead of refusing,
but ONLY when the hook it would refuse to overwrite is recognizably this package's own --
never for a hook this package has never touched, however coincidentally its content is
shaped; refusing an unrecognized foreign hook is unchanged.

- **The first gate onto a hook name still gets exactly what it always got**: its own
  solo `GateSpec.shim`, byte for byte, at `<hooks_directory>/<hook_name>`. Nothing above
  changes for the common, single-gate-per-hook case.
- **A second (or third...) gate onto that same hook name** finds the hook already
  occupied by a shim this package recognizes as its own (see
  :func:`_looks_like_an_interlock_shim`) and converts it: the pre-existing gate's exact
  bytes move, UNMODIFIED, into their own file under
  `<hooks_directory>/interlock-composed/<hook_name>/<pre-existing gate's marker name>`;
  the new gate's own solo shim is written alongside it, under its own marker name; and
  `<hooks_directory>/<hook_name>` itself becomes :data:`COMPOSED_DISPATCHER_SHIM` -- a
  second, equally fixed, equally byte-frozen constant that holds no gate logic either, and
  whose only job is to run every file under its own `interlock-composed/<hook_name>/`
  directory in turn, stopping at the first one that refuses. No gate's own dispatch logic
  is re-derived, parsed, or reconstructed from another gate's shim text to do this --
  every component file is either an untouched copy of a real, tested solo shim, or the
  fixed dispatcher constant.
- **A hook already occupied by a genuinely foreign file** (this package never wrote it,
  and its content matches neither a solo shim nor the composed dispatcher) is still
  refused exactly as before -- this package still never silently rewrites content it does
  not recognize as its own.
- **`docs/INTEGRATION.md` Section 5's hand-composed alternative is unaffected** and still
  works; :func:`installation_state` recognizes it too (by the same two strings -- a
  gate's own marker name and its own CLI module path -- that section's worked example
  necessarily names), so `interlock status` no longer calls a correctly-enforcing,
  hand-composed hook "FOREIGN" either.
"""
from __future__ import annotations

import hashlib
import re
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
    ``cli_module`` and ``gate_label`` are carried alongside the shim -- not only for
    rendering it in the first place -- so this dataclass is fully self-describing: see
    :func:`installation_state` and :func:`install`'s composing branch, both of which need
    to recognize or reproduce a gate's own dispatch without a second, independently
    passed copy of the same two strings.
    """

    marker_name: str
    hook_name: str
    shim: str
    cli_module: str
    gate_label: str


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


#: The composed dispatcher `install` writes to `<hooks_directory>/<hook_name>` once a
#: second gate needs to share a hook name already occupied by one of this package's own
#: solo shims. Fixed and byte-frozen exactly like a solo shim (see `render_shim`'s own
#: docstring) -- it embeds no gate-specific or machine-specific text at all, resolving
#: which hook name it is serving, and which components to run, entirely at runtime via
#: `$0`. See the module docstring's "Composing more than one gate onto a shared hook
#: name" section for the full design.
COMPOSED_DISPATCHER_SHIM = """#!/bin/sh
# interlock (git): composed multi-gate dispatcher. INSTALLED, NOT TRACKED.
#
# This file deliberately holds no gate logic, exactly like a solo gate's own shim (see
# render_shim's own docstring). More than one gate shares this hook name -- git dispatches
# exactly one file per hook name -- so `interlock install` composed this dispatcher itself
# rather than refusing the second gate onto it (see docs/INTEGRATION.md Section 5 for the
# hand-composed alternative this supersedes for the common case, still supported).
#
# Each gate's own component file, alongside this one under
# `interlock-composed/<hook name>/`, is byte-identical to what installing that gate ALONE
# onto this hook name would have written -- this dispatcher only sequences them, in
# whatever order the shell's own glob expansion returns, stopping at the first one that
# refuses.
set -e
hook_name="$(basename "$0")"
components_dir="$(dirname "$0")/interlock-composed/$hook_name"
[ -d "$components_dir" ] || exit 0
for component in "$components_dir"/*; do
    [ -f "$component" ] || continue
    sh "$component" || exit $?
done
"""

_INTERLOCK_SHIM_HEADER = "# interlock (git):"

#: Extracts the marker name out of a recognized solo shim's fixed template line, so an
#: existing gate's shim can be relocated into its own component file, unmodified, without
#: this module needing to already know which gate it belonged to. See
#: :func:`_existing_solo_marker_name`.
_MARKER_NAME_IN_SHIM = re.compile(r'gate_marker="\$gate_dir/([^"\n]+)"')


def _looks_like_an_interlock_shim(hook_text: str) -> bool:
    """Whether existing hook content was authored by this package -- a solo gate's own
    shim, or the composed dispatcher :func:`install` itself writes -- recognized by the
    fixed header line every shape this package writes carries. Never true for a hook this
    package has never touched, however coincidentally its content happens to be shaped:
    unrecognized content is always refused by :func:`install`, never silently rewritten.
    """
    lines = hook_text.splitlines()
    return len(lines) >= 2 and lines[0] == "#!/bin/sh" and lines[1].startswith(_INTERLOCK_SHIM_HEADER)


def _existing_solo_marker_name(existing_shim_text: str) -> str:
    """Best-effort extraction of the marker name a pre-existing solo shim (already
    confirmed to be this package's own, via :func:`_looks_like_an_interlock_shim`) was
    rendered for, so its exact bytes can be preserved, unmodified, as a named component
    when a second gate needs to share its hook name. Falls back to a stable hash of the
    content if the fixed template line is not found for some reason, so composing never
    depends on successfully identifying which gate a pre-existing shim belonged to --
    only on preserving its bytes under SOME stable name.
    """
    match = _MARKER_NAME_IN_SHIM.search(existing_shim_text)
    if match:
        return match.group(1)
    return "legacy-" + hashlib.sha256(existing_shim_text.encode("utf-8")).hexdigest()[:16]


def gate_marker_path(root: str | Path, spec: GateSpec) -> Path:
    """This worktree's own arming marker for ``spec`` -- present iff this worktree is
    armed."""
    return arming.marker_path(root, spec.marker_name)


def installed_hook_path(root: str | Path, spec: GateSpec) -> Path:
    """Where ``spec``'s shim belongs in the shared hooks directory."""
    return hooks_directory(root) / spec.hook_name


def _components_dir(root: str | Path, hook_name: str) -> Path:
    """Where composed component shims live for a given hook name -- see
    :data:`COMPOSED_DISPATCHER_SHIM`."""
    return hooks_directory(root) / "interlock-composed" / hook_name


def _component_path(root: str | Path, spec: GateSpec) -> Path:
    """Where ``spec``'s own component file lives once its hook name has been composed."""
    return _components_dir(root, spec.hook_name) / spec.marker_name


def is_armed(root: str | Path, spec: GateSpec) -> bool:
    """Whether THIS worktree has armed ``spec``. Says nothing about any other worktree."""
    return arming.is_armed(root, spec.marker_name)


def installation_state(root: str | Path, spec: GateSpec) -> tuple[bool, str]:
    """Whether ``spec``'s own gate is installed at its hook name, and a short, honest
    description of how that was determined.

    Used by ``interlock status`` so it never again conflates "not byte-identical to a
    solo shim" with "definitely unmanaged by this package" -- exactly the false alarm
    Finding 3 of ``REVIEW_2026-08-21.md`` raised: a hand-composed (and, before this
    module's own composing support, a would-be auto-composed) multi-gate hook was
    reported FOREIGN even though it was correctly armed and refusing real bad commits.

    Three ways this reports installed:

    - Byte-identical to ``spec``'s own solo shim -- the ordinary, single-gate case,
      unchanged from before.
    - The hook is :data:`COMPOSED_DISPATCHER_SHIM`, with a component file present for
      this exact gate -- what :func:`install` itself writes when a second gate needs to
      share an occupied hook name.
    - The hook's own text names both this gate's marker file and its CLI module path --
      the shape a hand-composed shim written per ``docs/INTEGRATION.md`` Section 5
      necessarily has, since that section's own worked example names both explicitly.
      Disclosed as a text-reference heuristic, not a semantic guarantee: this cannot
      verify what arbitrary hand-written shell actually does, only that it plausibly
      names this gate.

    Anything else is reported not-installed, distinguishing "nothing here" from "a
    composed dispatcher exists, but not for this gate" from "content this package does
    not recognize at all."
    """
    hook = installed_hook_path(root, spec)
    if not hook.is_file():
        return False, "not installed"
    existing = hook.read_bytes().decode("utf-8", errors="replace")
    if existing == spec.shim:
        return True, "installed"
    if existing == COMPOSED_DISPATCHER_SHIM:
        if _component_path(root, spec).is_file():
            return True, "installed (composed onto a hook shared with other interlock gates)"
        return False, (
            "a composed interlock dispatcher occupies this name, but has no component for "
            "this gate"
        )
    if spec.marker_name in existing and spec.cli_module in existing:
        return True, (
            "installed (a hand-composed hook per docs/INTEGRATION.md Section 5 names this "
            "gate -- confirmed by text reference only, not by execution)"
        )
    return False, "a FOREIGN hook occupies this name"


def install(root: str | Path, spec: GateSpec, *, interpreter: str | Path) -> tuple[str, ...]:
    """Write ``spec``'s shim into the shared hooks directory and arm THIS worktree only.

    **Refuses rather than overwrites a foreign hook.** If something this package does not
    recognize already occupies ``<hooks_directory>/<hook_name>``, this raises rather than
    clobbering it -- this package has no authority to decide how its own gate should
    coexist with a hook it never wrote. Idempotent when the installed hook is already this
    exact shim, or already composed in.

    **Composes automatically onto a hook name already occupied by another of this
    package's OWN gates**, rather than refusing -- see the module docstring's "Composing
    more than one gate onto a shared hook name" section for the full design and why this
    is safe precisely because it only ever happens onto content this package itself wrote.
    """
    root = Path(root)
    interpreter = Path(interpreter)
    if not interpreter.is_file():
        raise GateError(f"the interpreter to record does not exist: {interpreter}")
    actions: list[str] = []
    hook = installed_hook_path(root, spec)
    hook.parent.mkdir(parents=True, exist_ok=True)

    if not hook.is_file():
        hook.write_text(spec.shim, encoding="utf-8", newline="")
        hook.chmod(0o755)
        actions.append(f"hook installed: {hook}")
    else:
        # Byte-exact. Deliberately not `read_text(newline="")`: that keyword reached
        # `Path.read_text` only in Python 3.13, so on an older, still-supported interpreter
        # it is a TypeError rather than a strict read.
        existing = hook.read_bytes().decode("utf-8", errors="replace")
        if existing == spec.shim:
            actions.append(f"hook already current: {hook}")
        elif existing == COMPOSED_DISPATCHER_SHIM:
            component = _component_path(root, spec)
            if component.is_file():
                actions.append(f"gate already composed in: {component}")
            else:
                component.parent.mkdir(parents=True, exist_ok=True)
                component.write_text(spec.shim, encoding="utf-8", newline="")
                component.chmod(0o755)
                actions.append(f"gate composed onto the existing dispatcher: {component}")
        elif _looks_like_an_interlock_shim(existing):
            # Another of this package's own gates already owns this hook name as a solo
            # shim. Git dispatches exactly one file per hook name, and this package has
            # full authority over content it wrote itself -- so convert rather than
            # refuse: the pre-existing gate's exact bytes move, unmodified, into their own
            # component file, and this hook name becomes the fixed composed dispatcher.
            components_dir = _components_dir(root, spec.hook_name)
            components_dir.mkdir(parents=True, exist_ok=True)
            existing_marker = _existing_solo_marker_name(existing)
            existing_component = components_dir / existing_marker
            existing_component.write_text(existing, encoding="utf-8", newline="")
            existing_component.chmod(0o755)
            new_component = components_dir / spec.marker_name
            new_component.write_text(spec.shim, encoding="utf-8", newline="")
            new_component.chmod(0o755)
            hook.write_text(COMPOSED_DISPATCHER_SHIM, encoding="utf-8", newline="")
            hook.chmod(0o755)
            actions.append(
                f"hook composed: {hook} is now a multi-gate dispatcher (the pre-existing "
                f"gate moved, unmodified, to {existing_component}; this gate added at "
                f"{new_component})"
            )
        else:
            raise GateError(
                f"a {spec.hook_name} hook that is not this shim is already installed at "
                f"{hook}; refusing to overwrite it. Something else may own it -- inspect it, "
                "and if it is genuinely stale remove it deliberately before reinstalling. "
                "See docs/INTEGRATION.md if you need this gate to coexist with an existing "
                "hook of the same name."
            )
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
    "COMPOSED_DISPATCHER_SHIM", "GateSpec", "arm_marker", "gate_marker_path", "install",
    "installation_state", "installed_hook_path", "is_armed", "render_shim",
)
