# SPDX-License-Identifier: Apache-2.0
"""The turn-boundary half of the one install-and-arm discipline. Read
:mod:`interlock.arming` first -- this module is the thin, host-specific layer on top of it
that every hook in :mod:`interlock.turn` checks before doing anything else.

## What is identical to `interlock.git`

The marker itself: a per-worktree file under `git rev-parse --git-dir`, read and written by
the exact same :func:`interlock.arming.is_armed` / :func:`interlock.arming.arm` /
:func:`interlock.arming.disarm` primitives `interlock.git.hookkit` builds its own installer
on. Two hooks armed side by side -- one `interlock.git` gate, one `interlock.turn` hook --
have their markers sitting in the very same directory, written by the very same function.
An unarmed hook is a SILENT no-op, exactly like an unarmed git shim: nothing printed,
nothing blocked, nothing reminded. And arming is disclosed every time, never silent,
exactly as it is for a git gate.

## What structurally cannot be identical, and why

A git gate's `install()` does two things: write a fixed shell shim into the shared hooks
directory (the WIRING, shared across every worktree), and arm this worktree's own marker.
A turn-boundary hook has no shim to write. An AI coding harness invokes whatever command a
`settings.json`-style configuration names, directly -- there is no git-style
single-file-per-event indirection this package could install into even if it wanted to,
because the harness dispatches straight to the configured command with no intermediate
file of its own. So `interlock.turn`'s own WIRING step is, and remains, the same manual,
disclosed edit to `settings.json` that `docs/INTEGRATION.md` has always documented -- this
package does not, and structurally cannot, write that file for you the way it writes a git
hook shim, because there is no equivalent shared indirection layer to write into.

What consolidation genuinely adds is the ARMING half only: before this framework, every
hook here ran, unconditionally, the instant it was wired in, in every worktree that
`settings.json` reached -- there was no marker concept at all. Now each hook checks its own
per-worktree marker via this module before doing anything else, exactly mirroring the git
side's "installed but not yet armed does nothing." :func:`install_note` reflects this
honestly: for a turn hook, "install" arms the marker AND prints the `settings.json` entry
to add yourself, rather than writing that file -- it is advisory, not mutating, and says so.

## Failure direction: unarmed on any doubt

:func:`is_armed` never raises. If the repository root cannot be found, or the marker
cannot be read for any reason, it returns ``False`` -- "cannot determine armed" resolves
to "not armed," which resolves to "this hook does nothing," matching the git host's own
shim behaviour when its own marker read fails for any reason. This is consistent with, not
a departure from, `interlock.git`'s fail-closed posture: the shim's own *marker check* is
unconditionally silent-and-do-nothing on absence, and only the CHECK ITSELF (once armed
and running) fails closed. Arming status is a gate on whether to run at all, not the
check's own verdict, on both hosts alike.
"""
from __future__ import annotations

from pathlib import Path

from interlock import arming as _arming
from interlock.plumbing import repository_root as _repository_root

#: Every turn-boundary hook this host ships, and the exact marker name each one checks.
#: Append-only for the lifetime of this package -- see `RELEASE_PROCESS.md`: renaming an
#: entry silently unarms every worktree already armed under the old name.
HOOK_MARKER_NAMES: dict[str, str] = {
    "role_label": "interlock-turn-role-label",
    "announced_action": "interlock-turn-announced-action",
    "idle_roster": "interlock-turn-idle-roster",
    "roster_reconciliation": "interlock-turn-roster-reconciliation",
    "subagent_start": "interlock-turn-subagent-start",
    "subagent_stop": "interlock-turn-subagent-stop",
    "user_prompt_submit": "interlock-turn-user-prompt-submit",
}


def marker_name_for(hook: str) -> str:
    try:
        return HOOK_MARKER_NAMES[hook]
    except KeyError:
        raise ValueError(f"unknown interlock.turn hook: {hook!r}") from None


def is_armed(hook: str, *, root: Path | None = None) -> bool:
    """Whether THIS worktree has armed ``hook``. Never raises -- see module docstring on
    why "cannot tell" resolves to ``False``, the same direction an unarmed marker read
    resolves in on the git side."""
    try:
        resolved_root = root if root is not None else _repository_root()
        if resolved_root is None:
            return False
        return _arming.is_armed(resolved_root, marker_name_for(hook))
    except Exception:
        return False


def arm(hook: str, *, root: Path | None = None) -> str:
    """Write (or confirm) this worktree's own marker for ``hook``. Disclosed, never silent."""
    import datetime

    resolved_root = root if root is not None else _repository_root()
    if resolved_root is None:
        raise ValueError("not inside a git working tree -- cannot resolve a per-worktree marker location")
    content = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return _arming.arm(resolved_root, marker_name_for(hook), content)


def disarm(hook: str, *, root: Path | None = None) -> str:
    """Remove this worktree's own marker for ``hook``, if present. Disclosed, never silent."""
    resolved_root = root if root is not None else _repository_root()
    if resolved_root is None:
        raise ValueError("not inside a git working tree -- cannot resolve a per-worktree marker location")
    return _arming.disarm(resolved_root, marker_name_for(hook))


def install_note(hook: str, *, command: str) -> str:
    """The advisory text `interlock install turn.<hook>` prints alongside arming: the exact
    `settings.json` entry to add yourself. Never written to disk -- see the module
    docstring on why this host cannot install its own wiring the way `interlock.git` does.
    """
    return (
        f"This arms {hook!r} in this worktree. It does NOT wire the hook into your "
        f"harness's settings.json -- there is no shared indirection layer this package "
        f"can install into the way a git hook shim is installed. Add this yourself if "
        f"you have not already (see docs/INTEGRATION.md):\n\n"
        f'  {{ "type": "command", "command": "{command}" }}\n'
    )


__all__ = (
    "HOOK_MARKER_NAMES", "arm", "disarm", "install_note", "is_armed", "marker_name_for",
)
