# SPDX-License-Identifier: Apache-2.0
"""The table of every installable gate and hook this distribution ships, by identifier.

This is what makes ``interlock install|arm|disarm|status`` a single command over both
host modules rather than two hosts each keeping their own installer surface. An
identifier has the shape ``<host>.<name>`` -- ``git.protected-paths``,
``turn.idle-roster`` -- hyphenated for the shell, corresponding one-to-one with the
predicate or hook module's own dotted Python path with underscores
(``interlock.git.protected_paths``, ``interlock.turn.idle_roster``): see ``README.md``'s
"naming a gate" section.

Importing this module imports both :mod:`interlock.git` and :mod:`interlock.turn` -- it
is the one place in this distribution that legitimately needs both, because a CLI that
dispatches by identifier across both hosts has to know both. This is different from every
other module in either host subpackage, none of which imports its sibling -- see
``README.md``'s section on independent adoption. An adopter who only ever calls
`interlock.git.hookkit.install` directly, or only ever imports `interlock.turn.role_label`,
never touches this module and never pays for the import of the host they are not using.
"""
from __future__ import annotations

from dataclasses import dataclass

from interlock.git import (
    absolute_local_path, commit_message_pattern, protected_paths, stash_invocation,
    synthetic_git_identity,
)
from interlock.git.hookkit import GateSpec
from interlock.turn.arming import HOOK_MARKER_NAMES


@dataclass(frozen=True)
class GitGateEntry:
    id: str
    label: str
    spec: GateSpec
    module: str


@dataclass(frozen=True)
class TurnHookEntry:
    id: str
    label: str
    hook_key: str
    module: str
    command: str


GIT_GATES: tuple[GitGateEntry, ...] = (
    GitGateEntry(
        "git.protected-paths", protected_paths.GATE_LABEL, protected_paths.SPEC,
        "interlock.git.protected_paths",
    ),
    GitGateEntry(
        "git.absolute-local-path", absolute_local_path.GATE_LABEL, absolute_local_path.SPEC,
        "interlock.git.absolute_local_path",
    ),
    GitGateEntry(
        "git.commit-message-pattern", commit_message_pattern.GATE_LABEL, commit_message_pattern.SPEC,
        "interlock.git.commit_message_pattern",
    ),
    GitGateEntry(
        "git.stash-invocation", stash_invocation.GATE_LABEL, stash_invocation.SPEC,
        "interlock.git.stash_invocation",
    ),
    GitGateEntry(
        "git.synthetic-git-identity", synthetic_git_identity.GATE_LABEL, synthetic_git_identity.SPEC,
        "interlock.git.synthetic_git_identity",
    ),
)

#: hook_key must match a key in `interlock.turn.arming.HOOK_MARKER_NAMES` exactly.
TURN_HOOKS: tuple[TurnHookEntry, ...] = (
    TurnHookEntry(
        "turn.role-label", "role-label hook", "role_label", "interlock.turn.role_label",
        "python -m interlock.turn.role_label",
    ),
    TurnHookEntry(
        "turn.announced-action", "announced-action hook", "announced_action",
        "interlock.turn.announced_action", "python -m interlock.turn.announced_action",
    ),
    TurnHookEntry(
        "turn.idle-roster", "idle-roster hook", "idle_roster", "interlock.turn.idle_roster",
        "python -m interlock.turn.idle_roster",
    ),
    TurnHookEntry(
        "turn.roster-reconciliation", "roster-reconciliation hook", "roster_reconciliation",
        "interlock.turn.roster_reconciliation", "python -m interlock.turn.roster_reconciliation",
    ),
    TurnHookEntry(
        "turn.subagent-start", "subagent-start hook", "subagent_start",
        "interlock.turn.subagent_start", "python -m interlock.turn.subagent_start",
    ),
    TurnHookEntry(
        "turn.subagent-stop", "subagent-stop hook", "subagent_stop",
        "interlock.turn.subagent_stop", "python -m interlock.turn.subagent_stop",
    ),
    TurnHookEntry(
        "turn.user-prompt-submit", "user-prompt-submit hook", "user_prompt_submit",
        "interlock.turn.user_prompt_submit", "python -m interlock.turn.user_prompt_submit",
    ),
)

assert {h.hook_key for h in TURN_HOOKS} == set(HOOK_MARKER_NAMES), (
    "TURN_HOOKS and interlock.turn.arming.HOOK_MARKER_NAMES have drifted apart"
)


def all_ids() -> tuple[str, ...]:
    return tuple(g.id for g in GIT_GATES) + tuple(h.id for h in TURN_HOOKS)


def find_git_gate(identifier: str) -> GitGateEntry | None:
    return next((g for g in GIT_GATES if g.id == identifier), None)


def find_turn_hook(identifier: str) -> TurnHookEntry | None:
    return next((h for h in TURN_HOOKS if h.id == identifier), None)


__all__ = (
    "GIT_GATES", "TURN_HOOKS", "GitGateEntry", "TurnHookEntry", "all_ids", "find_git_gate",
    "find_turn_hook",
)
