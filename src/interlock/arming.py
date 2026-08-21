# SPDX-License-Identifier: Apache-2.0
"""The one install-and-arm discipline, shared by both host modules.

This is the part of the mechanism class that has nothing to do with git specifically or
with any one gate's or hook's own predicate: a per-worktree marker file that decides
whether a check installed somewhere SHARED actually does anything in THIS worktree.

## Why arming is per-worktree while wiring is shared

A repository's hooks resolve through its COMMON git directory (`git rev-parse
--git-common-dir`), which every linked worktree of a checkout shares -- installing a git
hook from any one worktree makes it fire in all of them, including a worktree some other,
unrelated stream of work owns. An AI coding harness's own hook configuration
(`settings.json` or equivalent) is comparably shared whenever it is tracked, committed
project content: every worktree checking out the same commit sees the same wiring.
Silently imposing a check on work that never agreed to it is an act with a blast radius
across everyone sharing that checkout, so both hosts separate the two: wiring (a git hook
shim installed once into the shared hooks directory, or a hook command entry in a shared
`settings.json`) is a no-op by default, and each worktree independently decides whether to
arm itself by writing a marker file inside `git rev-parse --git-dir`, which resolves
SEPARATELY for each worktree even though the wiring does not.

**This module is the whole reason `interlock.turn`'s hooks can share this discipline with
`interlock.git`'s gates at all.** The former framework this package's turn-boundary half was
extracted from had no marker concept whatsoever -- every hook, once wired into
`settings.json`, simply ran, unconditionally, in every worktree that configuration
reached. `interlock.git.hookkit` builds its shim-and-marker installer on top of the primitives
here; every hook in `interlock.turn` checks its own marker (via
`interlock.turn.arming.is_armed`) at the top of its own `main()`, before doing anything else --
see that module for the one place the two hosts' arming genuinely differ, and why.

## Why this module is host-neutral

Nothing here knows what is being armed, or what "armed" causes to happen once checked --
it only reads and writes one small file, disclosing every change it makes. That is
deliberate: the git-specific half of installation (a shell shim, `GateSpec`, refusing to
overwrite a foreign hook file) stays in `interlock.git.hookkit`, and the turn-boundary-specific
half (which hook module checks which marker, and what "unarmed" means for a reminder
versus a refusal) stays in `interlock.turn.arming`. This module is the one thing both actually
share: read a marker, write a marker, say what changed.
"""
from __future__ import annotations

from pathlib import Path

from interlock.plumbing import worktree_git_dir


def marker_path(root: str | Path, marker_name: str) -> Path:
    """THIS worktree's own marker file for ``marker_name``.

    Always under `git rev-parse --git-dir` -- per-worktree by construction, even though a
    linked worktree's HOOKS directory (git's, or a harness's shared `settings.json`) is
    not. See the module docstring for why that distinction is the entire point.
    """
    return worktree_git_dir(root) / marker_name


def is_armed(root: str | Path, marker_name: str) -> bool:
    """Whether THIS worktree has armed ``marker_name``. Says nothing about any other
    worktree, and nothing about whether whatever ``marker_name`` gates is even wired in."""
    return marker_path(root, marker_name).is_file()


def read_marker(root: str | Path, marker_name: str) -> str | None:
    """The marker's own recorded content (stripped), or ``None`` if this worktree is not
    armed."""
    path = marker_path(root, marker_name)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def arm(root: str | Path, marker_name: str, content: str) -> str:
    """Write (or confirm) THIS worktree's own marker for ``marker_name``. Idempotent.

    Returns a disclosure string describing what happened -- arming is never silent, even
    when it turns out to be a no-op because this worktree was already armed with the
    identical content.
    """
    path = marker_path(root, marker_name)
    if path.is_file() and path.read_text(encoding="utf-8").strip() == content:
        return f"worktree already armed: {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8", newline="\n")
    return f"worktree armed: {path}"


def disarm(root: str | Path, marker_name: str) -> str:
    """Remove THIS worktree's own marker for ``marker_name``, if present. Idempotent, and
    just as disclosed as arming -- silently leaving a marker in place after a claimed
    disarm would be exactly the invisible-gap this whole mechanism exists to prevent."""
    path = marker_path(root, marker_name)
    if not path.is_file():
        return f"worktree already unarmed: {path}"
    path.unlink()
    return f"worktree unarmed: {path}"


__all__ = ("arm", "disarm", "is_armed", "marker_path", "read_marker")
