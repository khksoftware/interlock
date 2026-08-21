# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`interlock.plumbing`, shared by both hosts."""
from __future__ import annotations

from pathlib import Path

import pytest

from interlock.errors import GateError
from interlock.plumbing import (
    commit_paths, effective_git_config, hooks_directory, index_blob, repository_root,
    working_tree_root, worktree_git_dir,
)
from tests.conftest import run_git


class TestTheBasics:
    def test_working_tree_root_resolves_the_top(self, sandbox: Path) -> None:
        nested = sandbox / "a" / "b"
        nested.mkdir(parents=True)
        assert working_tree_root(nested) == sandbox.resolve()

    def test_working_tree_root_refuses_outside_a_repository(self, tmp_path: Path) -> None:
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        with pytest.raises(GateError):
            working_tree_root(outside)

    def test_worktree_git_dir_is_the_dot_git_directory(self, sandbox: Path) -> None:
        assert worktree_git_dir(sandbox) == (sandbox / ".git").resolve()

    def test_hooks_directory_defaults_to_common_dir_hooks(self, sandbox: Path) -> None:
        assert hooks_directory(sandbox) == (sandbox / ".git" / "hooks").resolve()

    def test_hooks_directory_honours_core_hooks_path(self, sandbox: Path) -> None:
        custom = sandbox / "custom-hooks"
        custom.mkdir()
        run_git(sandbox, "config", "core.hooksPath", "custom-hooks")
        assert hooks_directory(sandbox) == custom.resolve()


class TestCommitPathsAndIndexBlob:
    def test_commit_paths_on_a_root_commit_lists_every_cached_path(self, tmp_path: Path) -> None:
        root = tmp_path / "fresh"
        root.mkdir()
        run_git(root, "init", "-q")
        (root / "one.txt").write_text("one\n", encoding="utf-8")
        (root / "two.txt").write_text("two\n", encoding="utf-8")
        run_git(root, "add", "one.txt", "two.txt")
        assert set(commit_paths(root)) == {"one.txt", "two.txt"}

    def test_commit_paths_after_head_lists_only_staged_changes(self, sandbox: Path) -> None:
        (sandbox / "new.txt").write_text("new\n", encoding="utf-8")
        run_git(sandbox, "add", "new.txt")
        assert commit_paths(sandbox) == ("new.txt",)

    def test_index_blob_reads_staged_content_not_the_working_tree(self, sandbox: Path) -> None:
        target = sandbox / "README.md"
        run_git(sandbox, "add", "README.md")  # already committed; re-add is a no-op
        target.write_text("changed on disk, never staged\n", encoding="utf-8")
        assert index_blob(sandbox, "README.md") == "sandbox\n"

    def test_index_blob_is_none_for_a_deleted_path(self, sandbox: Path) -> None:
        run_git(sandbox, "rm", "-q", "README.md")
        assert index_blob(sandbox, "README.md") is None


class TestEffectiveGitConfig:
    def test_returns_none_when_unset(self, sandbox: Path) -> None:
        assert effective_git_config(sandbox, "made.up.key") is None

    def test_local_overrides_global_resolution(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "local@sandbox.test")
        assert effective_git_config(sandbox, "user.email") == "local@sandbox.test"


class TestRepositoryRootNeverRaises:
    """`repository_root` is `interlock.turn`'s own fail-open counterpart to
    `working_tree_root` -- see `plumbing.py`'s module docstring on why both exist. Proven
    here rather than assumed: it must return the identical answer `working_tree_root` does
    on a real repository, and `None` (never an exception) everywhere that function raises.
    """

    def test_agrees_with_working_tree_root_inside_a_repository(self, sandbox: Path) -> None:
        assert repository_root(sandbox) == working_tree_root(sandbox)

    def test_returns_none_outside_a_repository_rather_than_raising(self, tmp_path: Path) -> None:
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert repository_root(outside) is None

    def test_returns_none_for_a_nonexistent_path_rather_than_raising(self, tmp_path: Path) -> None:
        assert repository_root(tmp_path / "does-not-exist-at-all") is None

    def test_defaults_to_the_current_directory_when_given_none(self, sandbox: Path, monkeypatch) -> None:
        monkeypatch.chdir(sandbox)
        assert repository_root(None) == sandbox.resolve()
