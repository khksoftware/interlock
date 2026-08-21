# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.absolute_local_path import (
    SPEC, staged_absolute_local_path_failures, staged_absolute_local_path_failures_from_config,
)
from interlock.git.hookkit import install, is_armed
from tests.conftest import run_git


class TestThePredicate:
    def test_a_windows_drive_letter_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(r"See C:\Users\jdoe\repo\file.py for details" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(sandbox)
        assert len(failures) == 1
        assert "notes.md:1" in failures[0]

    def test_a_posix_home_directory_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text("See /home/jdoe/project/file.py\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_macos_users_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text("See /Users/jdoe/project/file.py\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_unc_path_is_caught(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(r"See \\server\share\folder\file.py" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_relative_path_is_not_flagged(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text("See engineering/tests/thing.py\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()

    def test_two_patterns_on_one_line_collapse_to_one_finding(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(
            r"C:\one\path and /home/two/path on one line" + "\n", encoding="utf-8",
        )
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures(sandbox)) == 1

    def test_a_citation_exempts_one_named_line(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(r"Historical: C:\old\path was the old layout" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        failures = staged_absolute_local_path_failures(
            sandbox, citations=({"path": "notes.md", "line_contains": "Historical"},),
        )
        assert failures == ()

    def test_deferred_scope_exempts_a_whole_prefix(self, sandbox: Path) -> None:
        (sandbox / "fixtures").mkdir()
        (sandbox / "fixtures" / "sample.txt").write_text(r"C:\fake\example\path" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "fixtures/sample.txt")
        failures = staged_absolute_local_path_failures(
            sandbox, deferred_scope=({"path_prefix": "fixtures/"},),
        )
        assert failures == ()

    def test_a_deleted_path_is_not_scanned(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(r"C:\will\be\deleted" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        run_git(sandbox, "commit", "-q", "-m", "add notes with a path")
        run_git(sandbox, "rm", "-q", "notes.md")
        assert staged_absolute_local_path_failures(sandbox) == ()


class TestFromConfig:
    def test_reads_citations_and_deferred_scope_from_the_config_file(self, sandbox: Path) -> None:
        config = sandbox / "interlock.json"
        config.write_text(
            '{"absolute_local_path": {"deferred_scope": [{"path_prefix": "fixtures/"}]}}',
            encoding="utf-8",
        )
        run_git(sandbox, "add", "interlock.json")
        (sandbox / "fixtures").mkdir()
        (sandbox / "fixtures" / "sample.txt").write_text(r"C:\fake\path" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "fixtures/sample.txt")
        assert staged_absolute_local_path_failures_from_config(sandbox) == ()

    def test_no_config_file_means_the_built_in_patterns_alone_apply(self, sandbox: Path) -> None:
        (sandbox / "notes.md").write_text(r"C:\no\config\here" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "notes.md")
        assert len(staged_absolute_local_path_failures_from_config(sandbox)) == 1


class TestTheBlockActuallyBlocks:
    def test_an_armed_worktree_refuses_a_real_commit_embedding_a_path(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "leak.md").write_text(r"C:\Users\jdoe\secret\notes" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "leak.md")
        result = run_git(sandbox, "commit", "-q", "-m", "oops")
        assert result.returncode != 0

    def test_an_unarmed_worktree_passes_the_identical_fixture(self, sandbox: Path, interpreter: Path) -> None:
        (sandbox / "leak.md").write_text(r"C:\Users\jdoe\secret\notes" + "\n", encoding="utf-8")
        run_git(sandbox, "add", "leak.md")
        result = run_git(sandbox, "commit", "-q", "-m", "unarmed, lands anyway")
        assert result.returncode == 0
        assert not is_armed(sandbox, SPEC)

    def test_an_ordinary_commit_passes_while_armed(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "ordinary.txt").write_text("nothing to see here\n", encoding="utf-8")
        run_git(sandbox, "add", "ordinary.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "ordinary")
        assert result.returncode == 0
