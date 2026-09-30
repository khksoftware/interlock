# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.registry` -- the id table the unified `interlock` CLI dispatches through."""
from __future__ import annotations

from interlock import registry


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


class TestEveryTurnHookKeyHasAMarkerName:
    def test_hook_keys_match_arming_registrations(self) -> None:
        from interlock.turn.arming import HOOK_MARKER_NAMES

        for hook in registry.TURN_HOOKS:
            assert hook.hook_key in HOOK_MARKER_NAMES


class TestFindGuardHook:
    def test_known_id_resolves(self) -> None:
        hook = registry.find_guard_hook("guard.execution-guard")
        assert hook is not None
        assert hook.module == "interlock.guard.execution_guard"
        assert hook.hook_key == "execution_guard"

    def test_unknown_id_returns_none(self) -> None:
        assert registry.find_guard_hook("guard.does-not-exist") is None


class TestEveryGuardHookKeyHasAMarkerName:
    def test_hook_keys_match_arming_registrations(self) -> None:
        from interlock.guard.arming import HOOK_MARKER_NAMES

        for hook in registry.GUARD_HOOKS:
            assert hook.hook_key in HOOK_MARKER_NAMES
