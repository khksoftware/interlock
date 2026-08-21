# SPDX-License-Identifier: Apache-2.0
"""Refuse a commit that touches a path an adopter has declared off-limits without authorization.

## The gap this closes

Some paths in a repository must not move except by an explicit, out-of-band decision: a
legal or compliance-owned directory, a vendored dependency nobody should hand-edit, a
release-signing config, the very gate modules and hook shims this package installs. The rule
protecting such a path is usually written down somewhere -- a CONTRIBUTING file, a standing
instruction, a brief -- and, exactly like every other rule this package's README motivates,
that is prose. It reaches a dispatch, an onboarding, a hurried afternoon; it does not reach
the moment someone's tooling is about to stage a change under that path.

This gate is the corrective: an exact-path or exact-prefix registry an adopter maintains, and
a refusal that fires on any commit whose changed-path set intersects it, with no exemption
and no heuristic. Membership, not content -- adding, editing, or DELETING a registered path is
refused identically, because deleting a protected file defeats whatever protected it at least
as thoroughly as editing it would.

## Why exact paths/prefixes, not a heuristic

"Which paths are protected" is a decision an adopter makes, not something this package can
infer from a file's name, location, or content. A content-based heuristic ("looks like a
config file," "looks generated") both under-matches (misses a protected file that does not
look special) and over-matches (catches an unrelated file that happens to look similar) --
the same failure mode an exact registry has no room for. So the registry here is exactly what
the adopter writes down: a tuple of exact repository-relative paths, and/or a tuple of prefix
strings under which everything is protected.

## Scope: this commit's own changed-path set, nothing repository-wide

Exactly like every other gate in this package, this predicate is scoped to what THIS commit
would actually carry (:func:`interlock.plumbing.commit_paths`), never a
repository-wide walk. A commit that never touches a protected path is silent here even if the
tree elsewhere holds one; a concurrent, unrelated commit is never obstructed for a defect it
did not introduce or touch.

## What it does not reach, stated rather than implied

This gate has no notion of WHO is committing, only WHAT the commit's changed-path set
contains. A rule of the shape "only role X may touch this path" is not fully expressible here
-- see ``README.md``'s section on the mechanism class's own permanent blind spots, which names
this exact residue (a git commit carries no signal distinguishing which role or identity
authored it, even under the same git identity). What this gate DOES express -- "this path
does not move without an explicit, disclosed bypass" -- is the part of that rule a commit
hook can actually see.

And, like every hook-based gate, this one is bypassable: ``git commit --no-verify`` skips it,
``core.hooksPath`` can be repointed, and the arming marker can be deleted. It raises the cost
of an unauthorized change to a protected path reaching a commit; it does not make one
impossible.
"""
from __future__ import annotations

from pathlib import Path

from interlock.git.hookkit import GateSpec, render_shim
from interlock.plumbing import commit_paths

GATE_LABEL = "protected-paths gate"
GATE_MARKER_NAME = "interlock-git-protected-paths"
HOOK_NAME = "pre-commit"
CLI_MODULE = "interlock.git.cli.check_protected_paths"

SPEC = GateSpec(
    marker_name=GATE_MARKER_NAME,
    hook_name=HOOK_NAME,
    shim=render_shim(
        marker_name=GATE_MARKER_NAME, hook_name=HOOK_NAME, cli_module=CLI_MODULE,
        gate_label=GATE_LABEL,
    ),
)


def protected_path_failures(
    repository_root: str | Path, *,
    protected_paths: tuple[str, ...] = (), protected_prefixes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Every path in this commit's changed-path set that is protected.

    ``protected_paths`` is matched exactly; ``protected_prefixes`` matches any path starting
    with one of the given strings (typically a directory name ending in ``/``). Both are
    empty by default -- an adopter who calls this with no configuration gets a gate that
    protects nothing, which is correct: this gate has no opinion of its own about what matters
    in a repository it has never seen.
    """
    root = Path(repository_root)
    changed = commit_paths(root)
    exact = set(protected_paths)
    failures: list[str] = []
    for relative in changed:
        if relative in exact:
            failures.append(
                f"{relative}: this commit writes a path registered as protected "
                "(exact-path match); it does not move without an explicit, disclosed bypass."
            )
            continue
        matched_prefix = next(
            (prefix for prefix in protected_prefixes if relative.startswith(prefix)), None
        )
        if matched_prefix is not None:
            failures.append(
                f"{relative}: this commit writes under protected prefix {matched_prefix!r}; "
                "it does not move without an explicit, disclosed bypass."
            )
    return tuple(failures)


__all__ = (
    "CLI_MODULE", "GATE_LABEL", "GATE_MARKER_NAME", "HOOK_NAME", "SPEC",
    "protected_path_failures",
)
