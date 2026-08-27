# SPDX-License-Identifier: Apache-2.0
"""The ``interlock.guard`` half of the one install-and-arm discipline. Read
:mod:`interlock.arming` first -- this module is the thin, host-specific layer on top of it,
built the same way :mod:`interlock.turn.arming` is: a ``PreToolUse``-shaped hook has no shim
to install (an AI coding harness invokes whatever command its own hook configuration names,
directly, with no git-style indirection layer), so this host's ``install`` step is,
structurally, the same as `interlock.turn`'s -- arm the per-worktree marker, and print
(never write) the exact harness configuration entry to add. See that module's own docstring
for the full argument; it applies here unchanged, one host down.
"""
from __future__ import annotations

from pathlib import Path

from interlock import arming as _arming
from interlock.plumbing import repository_root as _repository_root

#: Every guard hook this host ships, and the exact marker name each one checks.
#: Append-only for the lifetime of this package -- see `RELEASE_PROCESS.md`: renaming an
#: entry silently unarms every worktree already armed under the old name.
HOOK_MARKER_NAMES: dict[str, str] = {
    "execution_guard": "interlock-guard-execution-guard",
}


def marker_name_for(hook: str) -> str:
    try:
        return HOOK_MARKER_NAMES[hook]
    except KeyError:
        raise ValueError(f"unknown interlock.guard hook: {hook!r}") from None


def is_armed(hook: str, *, root: Path | None = None) -> bool:
    """Whether THIS worktree has armed ``hook``. Never raises -- "cannot determine armed"
    resolves to ``False``, matching `interlock.turn.arming.is_armed`'s own reasoning."""
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
    """The advisory text `interlock install guard.<hook>` prints alongside arming: the exact
    harness hook-configuration entry to add yourself. Never written to disk -- see the
    module docstring on why this host cannot install its own wiring the way `interlock.git`
    does."""
    return (
        f"This arms {hook!r} in this worktree. It does NOT wire the hook into your "
        f"harness's own hook configuration -- there is no shared indirection layer this "
        f"package can install into the way a git hook shim is installed. Add this yourself "
        f"if you have not already (see docs/INTEGRATION.md):\n\n"
        f'  {{ "type": "command", "command": "{command}" }}\n'
    )


__all__ = (
    "HOOK_MARKER_NAMES", "arm", "disarm", "install_note", "is_armed", "marker_name_for",
)
