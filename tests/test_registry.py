# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.registry` -- the id table the unified `interlock` CLI
dispatches through.

Not to be confused with :mod:`interlock.turn.outstanding` (the best-effort dispatched-
agent bookkeeping file, a completely different thing this module used to share a name
with before the rename that resolved the collision -- see that module's own docstring).
"""
from __future__ import annotations

from interlock import registry


class TestAllIdsCoversEveryShippedCheck:
    def test_five_git_gates_and_seven_turn_hooks(self) -> None:
        git_ids = [i for i in registry.all_ids() if i.startswith("git.")]
        turn_ids = [i for i in registry.all_ids() if i.startswith("turn.")]
        assert len(git_ids) == 5
        assert len(turn_ids) == 7
        assert len(registry.all_ids()) == len(set(registry.all_ids())), "no duplicate ids"

    def test_every_id_is_hyphenated_not_underscored(self) -> None:
        for identifier in registry.all_ids():
            _, _, name = identifier.partition(".")
            assert "_" not in name, f"{identifier!r} should use hyphens in its name segment"


class TestFindGitGate:
    def test_known_id_resolves(self) -> None:
        gate = registry.find_git_gate("git.protected-paths")
        assert gate is not None
        assert gate.module == "interlock.git.protected_paths"

    def test_unknown_id_returns_none(self) -> None:
        assert registry.find_git_gate("git.does-not-exist") is None

    def test_a_turn_id_is_not_a_git_gate(self) -> None:
        assert registry.find_git_gate("turn.idle-roster") is None


class TestFindTurnHook:
    def test_known_id_resolves(self) -> None:
        hook = registry.find_turn_hook("turn.idle-roster")
        assert hook is not None
        assert hook.module == "interlock.turn.idle_roster"
        assert hook.hook_key == "idle_roster"

    def test_unknown_id_returns_none(self) -> None:
        assert registry.find_turn_hook("turn.does-not-exist") is None

    def test_a_git_id_is_not_a_turn_hook(self) -> None:
        assert registry.find_turn_hook("git.protected-paths") is None


class TestEveryTurnHookKeyHasAMarkerName:
    def test_hook_keys_match_arming_registrations(self) -> None:
        from interlock.turn.arming import HOOK_MARKER_NAMES

        for hook in registry.TURN_HOOKS:
            assert hook.hook_key in HOOK_MARKER_NAMES
