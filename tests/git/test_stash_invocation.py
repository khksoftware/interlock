# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.hookkit import install, is_armed
from interlock.git.stash_invocation import (
    SPEC, stash_invocation_refusal, transaction_touches_stash_ref,
)
from tests.conftest import run_git


class TestThePredicate:
    def test_a_prepared_transaction_touching_refs_stash_is_flagged(self) -> None:
        line = "0000000000000000000000000000000000000000 abc1234 refs/stash"
        assert transaction_touches_stash_ref("prepared", line) is True
        assert stash_invocation_refusal("prepared", line) is not None

    def test_committed_phase_is_never_actionable(self) -> None:
        line = "0000000000000000000000000000000000000000 abc1234 refs/stash"
        assert transaction_touches_stash_ref("committed", line) is False
        assert stash_invocation_refusal("committed", line) is None

    def test_an_unrelated_ref_is_not_flagged(self) -> None:
        line = "abc1234 def5678 refs/heads/main"
        assert transaction_touches_stash_ref("prepared", line) is False
        assert stash_invocation_refusal("prepared", line) is None

    def test_a_multi_line_batch_is_scanned_in_full(self) -> None:
        batch = "abc1234 def5678 refs/heads/main\n0000000000000000000000000000000000000000 abc1234 refs/stash\n"
        assert transaction_touches_stash_ref("prepared", batch) is True

    def test_blank_lines_are_ignored(self) -> None:
        assert transaction_touches_stash_ref("prepared", "\n\n") is False


class TestTheBlockActuallyBlocks:
    """A real `git stash` against a really-installed `reference-transaction` hook."""

    def test_an_armed_worktree_refuses_git_stash(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "README.md").write_text("uncommitted change\n", encoding="utf-8")
        result = run_git(sandbox, "stash")
        assert result.returncode != 0
        # The working tree is untouched by the refusal: the uncommitted change survives.
        assert (sandbox / "README.md").read_text(encoding="utf-8") == "uncommitted change\n"
        assert run_git(sandbox, "stash", "list").stdout.decode().strip() == ""

    def test_git_stash_clear_is_refused_when_a_stash_exists(self, sandbox: Path, interpreter: Path) -> None:
        (sandbox / "README.md").write_text("first change\n", encoding="utf-8")
        precondition = run_git(sandbox, "stash")  # unarmed here: this stash is allowed to land
        assert precondition.returncode == 0
        install(sandbox, SPEC, interpreter=interpreter)
        result = run_git(sandbox, "stash", "clear")
        assert result.returncode != 0
        assert run_git(sandbox, "stash", "list").stdout.decode().strip() != ""

    def test_an_unarmed_worktree_allows_git_stash(self, sandbox: Path) -> None:
        (sandbox / "README.md").write_text("uncommitted change\n", encoding="utf-8")
        result = run_git(sandbox, "stash")
        assert result.returncode == 0
        assert not is_armed(sandbox, SPEC)

    def test_no_verify_does_not_exist_for_stash_but_repointing_hookspath_bypasses_it(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        empty_hooks = sandbox / "no-hooks-here"
        empty_hooks.mkdir()
        run_git(sandbox, "config", "core.hooksPath", "no-hooks-here")
        (sandbox / "README.md").write_text("bypassed\n", encoding="utf-8")
        result = run_git(sandbox, "stash")
        assert result.returncode == 0
