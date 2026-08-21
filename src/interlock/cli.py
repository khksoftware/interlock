# SPDX-License-Identifier: Apache-2.0
"""The unified `interlock` command: install, arm, disarm, and status, across both hosts.

    interlock install  git.protected-paths
    interlock arm      git.protected-paths
    interlock disarm   git.protected-paths
    interlock status
    interlock status   turn.idle-roster

One surface, one identifier scheme (``<host>.<name>``, see :mod:`interlock.registry`),
covering both `interlock.git`'s gates and `interlock.turn`'s hooks -- before consolidation,
the git host had five separate `--install` flags scattered across five CLI modules and the
turn host had no install/arm/status surface of any kind. This module is what "one
install-and-arm discipline" means as a user-facing command, not only as shared library
code.

**`install` vs. `arm`, kept distinct on both hosts, for the same reason on both.** `arm`
only ever writes THIS worktree's own per-worktree marker -- the additive, always-safe
half. `install` does that AND whatever WIRING half a host has: for `interlock.git`, writing
the shared shell shim into the shared hooks directory (refusing to overwrite a foreign
hook); for `interlock.turn`, printing -- never writing -- the exact `settings.json` entry
to add yourself, because there is no shared indirection layer this package can install
into the way a git hook shim is installed (see :mod:`interlock.turn.arming`'s own
docstring for precisely why that asymmetry is structural, not an oversight).

**`status` reports what is installed and what is actually armed, separately, for every
id this distribution knows** (or one, if given). Conflating the two -- "installed" reading
as "therefore enforcing" -- is exactly the invisible gap arming exists to close; a status
command that only reported one of the two facts would reintroduce it in a different
place.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from interlock import arming as shared_arming
from interlock import registry
from interlock.errors import GateError
from interlock.git.hookkit import arm_marker, install, installation_state, is_armed as git_is_armed
from interlock.plumbing import working_tree_root
from interlock.turn import arming as turn_arming


def _git_root(args: argparse.Namespace) -> Path:
    """Raises :class:`GateError` if ``--repository-root`` was not given and the current
    directory is not inside a git working tree."""
    if args.repository_root is not None:
        return args.repository_root.resolve()
    return working_tree_root(Path.cwd())


def _unknown_id(identifier: str) -> str:
    return f"unknown id: {identifier!r}. Known ids:\n  " + "\n  ".join(registry.all_ids())


def cmd_install(args: argparse.Namespace) -> int:
    gate = registry.find_git_gate(args.id)
    if gate is not None:
        try:
            root = _git_root(args)
        except GateError as error:
            print(str(error), file=sys.stderr)
            return 2
        interpreter = args.interpreter if args.interpreter is not None else Path(sys.executable)
        try:
            for action in install(root, gate.spec, interpreter=interpreter):
                print(action)
        except GateError as error:
            print(f"{gate.label}: {error}", file=sys.stderr)
            return 2
        return 0

    hook = registry.find_turn_hook(args.id)
    if hook is not None:
        root = args.repository_root.resolve() if args.repository_root is not None else None
        try:
            print(turn_arming.arm(hook.hook_key, root=root))
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print()
        print(turn_arming.install_note(hook.hook_key, command=hook.command))
        return 0

    print(_unknown_id(args.id), file=sys.stderr)
    return 2


def cmd_arm(args: argparse.Namespace) -> int:
    gate = registry.find_git_gate(args.id)
    if gate is not None:
        try:
            root = _git_root(args)
        except GateError as error:
            print(str(error), file=sys.stderr)
            return 2
        interpreter = args.interpreter if args.interpreter is not None else Path(sys.executable)
        try:
            print(arm_marker(root, gate.spec, interpreter=interpreter))
        except GateError as error:
            print(f"{gate.label}: {error}", file=sys.stderr)
            return 2
        return 0

    hook = registry.find_turn_hook(args.id)
    if hook is not None:
        root = args.repository_root.resolve() if args.repository_root is not None else None
        try:
            print(turn_arming.arm(hook.hook_key, root=root))
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        return 0

    print(_unknown_id(args.id), file=sys.stderr)
    return 2


def cmd_disarm(args: argparse.Namespace) -> int:
    gate = registry.find_git_gate(args.id)
    if gate is not None:
        try:
            root = _git_root(args)
        except GateError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(shared_arming.disarm(root, gate.spec.marker_name))
        return 0

    hook = registry.find_turn_hook(args.id)
    if hook is not None:
        root = args.repository_root.resolve() if args.repository_root is not None else None
        try:
            print(turn_arming.disarm(hook.hook_key, root=root))
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        return 0

    print(_unknown_id(args.id), file=sys.stderr)
    return 2


def _git_status_line(gate: registry.GitGateEntry, root: Path | None) -> str:
    if root is None:
        return f"{gate.id:<28} [git ] not inside a git working tree"
    try:
        _, installed = installation_state(root, gate.spec)
    except GateError as error:
        return f"{gate.id:<28} [git ] {error}"
    armed = "armed" if git_is_armed(root, gate.spec) else "not armed"
    return f"{gate.id:<28} [git ] {installed}; {armed} in this worktree"


def _turn_status_line(hook: registry.TurnHookEntry, root: Path | None) -> str:
    armed = turn_arming.is_armed(hook.hook_key, root=root) if root is not None else False
    disposition = "armed" if armed else "not armed"
    return (
        f"{hook.id:<28} [turn] wiring is a manual settings.json edit (see "
        f"docs/INTEGRATION.md); {disposition} in this worktree"
    )


def cmd_status(args: argparse.Namespace) -> int:
    try:
        root = _git_root(args)
    except GateError:
        root = None

    ids = [args.id] if args.id else list(registry.all_ids())
    for identifier in ids:
        gate = registry.find_git_gate(identifier)
        if gate is not None:
            print(_git_status_line(gate, root))
            continue
        hook = registry.find_turn_hook(identifier)
        if hook is not None:
            print(_turn_status_line(hook, root))
            continue
        print(_unknown_id(identifier), file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="interlock",
        description=(
            "Install, arm, disarm, and report on interlock's git-action and agent-turn "
            "boundary checks, by one identifier scheme."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_install = subparsers.add_parser(
        "install", help="Full setup: git wiring+marker, or turn marker+wiring note",
    )
    p_install.add_argument("id")
    p_install.add_argument("--repository-root", type=Path, default=None)
    p_install.add_argument("--interpreter", type=Path, default=None)
    p_install.set_defaults(func=cmd_install)

    p_arm = subparsers.add_parser("arm", help="Arm this worktree only -- no wiring change")
    p_arm.add_argument("id")
    p_arm.add_argument("--repository-root", type=Path, default=None)
    p_arm.add_argument("--interpreter", type=Path, default=None)
    p_arm.set_defaults(func=cmd_arm)

    p_disarm = subparsers.add_parser("disarm", help="Remove this worktree's own marker")
    p_disarm.add_argument("id")
    p_disarm.add_argument("--repository-root", type=Path, default=None)
    p_disarm.set_defaults(func=cmd_disarm)

    p_status = subparsers.add_parser(
        "status", help="Report installed/armed state for one id, or every id",
    )
    p_status.add_argument("id", nargs="?", default=None)
    p_status.add_argument("--repository-root", type=Path, default=None)
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
