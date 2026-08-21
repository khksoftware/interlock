# SPDX-License-Identifier: Apache-2.0
"""Shared CLI plumbing: the exit-code contract and the boilerplate every `check_*` module uses.

Not a public API this package promises to keep stable across every minor release -- it
exists to keep the five `check_*` modules honest with each other rather than to be
imported by an adopter's own code. An adopter authoring a new gate's CLI is expected to
copy the shape (see ``docs/USAGE.md``), not necessarily import this module, though nothing
stops it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from interlock.errors import GateError
from interlock.git.hookkit import GateSpec, install
from interlock.plumbing import working_tree_root

EXIT_CLEAN = 0
EXIT_REFUSED = 1
EXIT_GATE_UNAVAILABLE = 2


def resolve_root(repository_root: Path | None) -> Path:
    return repository_root.resolve() if repository_root is not None else working_tree_root(Path.cwd())


def report_gate_unavailable(gate_label: str, cli_module: str, detail: str) -> int:
    """The gate could not run, so it refuses -- and says how to get past itself.

    A fail-closed control's own failure mode is not hypothetical: a moved interpreter, an
    unreadable marker, a corrupt index. It still refuses. An unverifiable action is not a
    verified one, and a gate that waves an action through on its own malfunction is a gate
    that fails at exactly the moment it is being relied on. The escape route (`--no-verify`)
    is named explicitly rather than left for an operator to rediscover under pressure, and the
    message asks for it to be disclosed, since nothing mechanical here can observe that it was
    used.
    """
    print(f"{gate_label}: {detail}", file=sys.stderr)
    print(
        "The gate could not run, so it REFUSES rather than passing the action unchecked: an "
        "unverifiable action is not a verified one. This is not a verdict about your change.",
        file=sys.stderr,
    )
    print(
        f"Repair it with: <interpreter> -B -m {cli_module} --install, run from this "
        "worktree.",
        file=sys.stderr,
    )
    print(
        "If you must proceed before the gate is repaired, `--no-verify` (or, for the "
        "stash-invocation gate, repointing core.hooksPath) skips this hook. Nothing "
        "mechanical records that you did, so SAY SO in your own report -- an undisclosed "
        "bypass leaves nobody able to tell which actions went unchecked.",
        file=sys.stderr,
    )
    return EXIT_GATE_UNAVAILABLE


def run_install(root: Path, spec: GateSpec, interpreter: Path, gate_label: str) -> int:
    try:
        for action in install(root, spec, interpreter=interpreter):
            print(action)
    except GateError as error:
        print(f"{gate_label}: {error}", file=sys.stderr)
        return EXIT_GATE_UNAVAILABLE
    return EXIT_CLEAN


__all__ = (
    "EXIT_CLEAN", "EXIT_GATE_UNAVAILABLE", "EXIT_REFUSED", "report_gate_unavailable",
    "resolve_root", "run_install",
)
