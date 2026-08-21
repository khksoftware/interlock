# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.hookkit import install
from interlock.git.synthetic_git_identity import SPEC, synthetic_identity_failures
from tests.conftest import run_git


class TestThePredicate:
    def test_an_ordinary_identity_is_clean(self, sandbox: Path) -> None:
        assert synthetic_identity_failures(sandbox) == ()

    def test_example_invalid_is_flagged(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "proof@example.invalid")
        failures = synthetic_identity_failures(sandbox)
        assert len(failures) == 1
        assert "example.invalid" in failures[0]

    def test_example_com_org_net_are_all_flagged(self, sandbox: Path) -> None:
        for domain in ("example.com", "example.org", "example.net"):
            run_git(sandbox, "config", "--local", "user.email", f"tester@{domain}")
            assert len(synthetic_identity_failures(sandbox)) == 1

    def test_localhost_is_flagged(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "tester@localhost")
        assert len(synthetic_identity_failures(sandbox)) == 1

    def test_a_lookalike_domain_is_not_flagged(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "tester@notexample.com")
        assert synthetic_identity_failures(sandbox) == ()

    def test_case_is_ignored(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "Tester@EXAMPLE.INVALID")
        assert len(synthetic_identity_failures(sandbox)) == 1


class TestTheBlockActuallyBlocks:
    def test_an_armed_worktree_refuses_a_commit_under_a_synthetic_identity(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        run_git(sandbox, "config", "--local", "user.email", "leftover@example.invalid")
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "should be refused")
        assert result.returncode != 0

    def test_an_unarmed_worktree_passes_the_identical_fixture(self, sandbox: Path) -> None:
        run_git(sandbox, "config", "--local", "user.email", "leftover@example.invalid")
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "unarmed, lands anyway")
        assert result.returncode == 0

    def test_an_ordinary_identity_passes_while_armed(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "ordinary identity, lands")
        assert result.returncode == 0
