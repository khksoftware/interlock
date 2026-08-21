# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from interlock.git.commit_message_pattern import (
    SPEC, commit_message_pattern_failures, staged_commit_message_pattern_failures_from_config,
)
from interlock.git.hookkit import install
from tests.conftest import run_git


class TestThePredicate:
    def test_a_vendor_attribution_trailer_is_flagged(self) -> None:
        message = "Fix the bug\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
        failures = commit_message_pattern_failures(message)
        assert len(failures) == 1
        assert "Claude" in failures[0]

    def test_a_human_co_author_is_not_flagged(self) -> None:
        message = "Fix the bug\n\nCo-Authored-By: Jane Doe <jane@example.invalid>\n"
        assert commit_message_pattern_failures(message) == ()

    def test_discussing_the_vendor_name_in_prose_is_not_flagged(self) -> None:
        message = "Add a gate that refuses Claude/Anthropic attribution trailers\n"
        assert commit_message_pattern_failures(message) == ()

    def test_trailer_key_matching_is_case_and_spacing_insensitive(self) -> None:
        message = "Fix\n\nco_authored_by: Codex <bot@example.invalid>\n"
        assert len(commit_message_pattern_failures(message)) == 1

    def test_a_non_attribution_trailer_key_is_out_of_scope(self) -> None:
        message = "Fix\n\nReviewed-by: Claude <noreply@anthropic.com>\n"
        assert commit_message_pattern_failures(message) == ()

    def test_a_custom_trailer_key_and_pattern_set_is_honoured(self) -> None:
        import re

        message = "Fix\n\nFixes: TICKET-1\n"
        patterns = (("bare ticket reference", re.compile(r"^TICKET-\d+$")),)
        failures = commit_message_pattern_failures(
            message, trailer_keys=frozenset({"fixes"}), forbidden_patterns=patterns,
        )
        assert len(failures) == 1


class TestFromConfig:
    def test_a_configured_trailer_key_set_overrides_the_default(self, sandbox: Path, tmp_path: Path) -> None:
        config = sandbox / "interlock.json"
        config.write_text('{"commit_message_pattern": {"trailer_keys": ["signed-off-by"]}}', encoding="utf-8")
        run_git(sandbox, "add", "interlock.json")
        run_git(sandbox, "commit", "-q", "-m", "configure trailer keys")
        message_file = tmp_path / "MSG"
        message_file.write_text("Fix\n\nSigned-off-by: Claude <noreply@anthropic.com>\n", encoding="utf-8")
        failures = staged_commit_message_pattern_failures_from_config(message_file, repository_root=sandbox)
        assert len(failures) == 1


class TestTheBlockActuallyBlocks:
    def test_an_armed_worktree_refuses_a_real_commit_with_a_vendor_trailer(
        self, sandbox: Path, interpreter: Path,
    ) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        message = "Add a file\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
        result = run_git(sandbox, "commit", "-q", "-F", "-", input_bytes=message.encode("utf-8"))
        assert result.returncode != 0

    def test_an_unarmed_worktree_passes_the_identical_fixture(self, sandbox: Path) -> None:
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        message = "Add a file\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
        result = run_git(sandbox, "commit", "-q", "-F", "-", input_bytes=message.encode("utf-8"))
        assert result.returncode == 0

    def test_an_ordinary_message_passes_while_armed(self, sandbox: Path, interpreter: Path) -> None:
        install(sandbox, SPEC, interpreter=interpreter)
        (sandbox / "file.txt").write_text("x\n", encoding="utf-8")
        run_git(sandbox, "add", "file.txt")
        result = run_git(sandbox, "commit", "-q", "-m", "an ordinary message")
        assert result.returncode == 0
