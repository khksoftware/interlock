# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.arming` -- the one marker primitive both hosts build their own install-and-arm discipline on."""
from __future__ import annotations

from pathlib import Path

from interlock.arming import arm, disarm, is_armed, marker_path, read_marker
from interlock.plumbing import worktree_git_dir


class TestMarkerPath:
    def test_lives_under_this_worktrees_own_git_dir(self, sandbox: Path) -> None:
        assert marker_path(sandbox, "some-marker") == worktree_git_dir(sandbox) / "some-marker"


class TestArmIsArmedDisarm:
    def test_a_fresh_worktree_is_not_armed(self, sandbox: Path) -> None:
        assert is_armed(sandbox, "example-marker") is False

    def test_arming_makes_it_armed(self, sandbox: Path) -> None:
        arm(sandbox, "example-marker", "some content")
        assert is_armed(sandbox, "example-marker") is True

    def test_arming_writes_the_given_content(self, sandbox: Path) -> None:
        arm(sandbox, "example-marker", "hello")
        assert read_marker(sandbox, "example-marker") == "hello"


    def test_arming_with_new_content_overwrites(self, sandbox: Path) -> None:
        arm(sandbox, "example-marker", "old")
        arm(sandbox, "example-marker", "new")
        assert read_marker(sandbox, "example-marker") == "new"

    def test_disarm_removes_the_marker(self, sandbox: Path) -> None:
        arm(sandbox, "example-marker", "content")
        disarm(sandbox, "example-marker")
        assert is_armed(sandbox, "example-marker") is False

    def test_disarm_is_idempotent_on_an_already_unarmed_worktree(self, sandbox: Path) -> None:
        message = disarm(sandbox, "never-armed-marker")
        assert "already unarmed" in message

    def test_disarming_discloses_what_happened(self, sandbox: Path) -> None:
        arm(sandbox, "example-marker", "content")
        message = disarm(sandbox, "example-marker")
        assert "unarmed" in message


class TestGitAndTurnMarkersCoexist:
    """The concrete claim this module's docstring makes: two markers with two different names, armed through the identical function, live in the same directory without interfering with each other --..."""

    def test_two_differently_named_markers_do_not_collide(self, sandbox: Path) -> None:
        arm(sandbox, "interlock-git-protected-paths", "/usr/bin/python3")
        arm(sandbox, "interlock-turn-idle-roster", "2026-01-01T00:00:00+00:00")

        assert is_armed(sandbox, "interlock-git-protected-paths") is True
        assert is_armed(sandbox, "interlock-turn-idle-roster") is True
        assert read_marker(sandbox, "interlock-git-protected-paths") == "/usr/bin/python3"
        assert read_marker(sandbox, "interlock-turn-idle-roster") == "2026-01-01T00:00:00+00:00"

        disarm(sandbox, "interlock-git-protected-paths")
        assert is_armed(sandbox, "interlock-git-protected-paths") is False
        # Disarming one must never touch the other.
        assert is_armed(sandbox, "interlock-turn-idle-roster") is True

